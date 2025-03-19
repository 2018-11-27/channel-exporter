# coding:utf-8
import os
import re
import sys
import time
import json
import functools
import threading

from datetime import datetime

if os.path.basename(sys.argv[0]) != 'setup.py':
    from prometheus_client import Histogram
    from prometheus_client import generate_latest
    from prometheus_client import start_http_server
    from prometheus_client import CONTENT_TYPE_LATEST

try:
    from flask import Flask
except ImportError:
    Flask = None
else:
    from flask import g
    from flask import request
    from flask import Response

    def wrap_flask_init_method(func):
        @functools.wraps(func)
        def inner(self, *a, **kw):
            func(self, *a, **kw)
            self.before_request(inner_metrics_before)
            self.after_request(inner_metrics)
            self.route('/metrics', methods=['GET'])(metrics)
        inner.__wrapped__ = func
        return inner

    def wrap_flask_run_method(func):
        @functools.wraps(func)
        def inner(*a, **kw):
            func(*a, **kw)
            Flask.__running__ = True
        inner.__wrapped__ = func
        return inner

    Flask.__init__ = wrap_flask_init_method(Flask.__init__)
    Flask.run = wrap_flask_run_method(Flask.run)

try:
    import requests
except ImportError:
    requests = None

try:
    from ctec_consumer.dummy.ctec_consumer import Consumer
except ImportError:
    Consumer = None
else:
    def wrap_register_worker(func):
        @functools.wraps(func)
        def inner(self, worker):
            worker = consumer_metrics(worker, topic=self.queue)
            func(self, worker)
        inner.__wrapped__ = func
        return inner

if sys.version_info.major < 3:
    from urlparse import urlparse
    is_char = lambda x: isinstance(x, (str, unicode))
else:
    from urllib.parse import urlparse
    is_char = lambda x: isinstance(x, str)

co_qualname = 'co_qualname' if sys.version_info >= (3, 11) else 'co_name'

this = sys.modules[__name__]

default_buckets = (
    100, 200, 500, 800, 1000, 1500, 2000, 2500, 3000, 4000, 5000, 6000, 8000
)


def __init__(
        syscode,
        inner_metrics_buckets=default_buckets,
        partner_http_metrics_buckets=default_buckets,
        consumer_metrics_buckets=default_buckets,
        default_metrics_port=9166,
):
    if hasattr(this, 'syscode'):
        return

    if re.match(r'[a-zA-Z]\d{9}$', syscode) is None:
        raise ValueError('parameter syscode "%s" is illegal.' % syscode)

    this.syscode = syscode = syscode.upper()
    this.appid = syscode[:4]

    if Flask is not None:
        this.metrics_inner = Histogram(
            name=syscode + '_inner_metrics',
            documentation='...',
            labelnames=(
                'appid', 'application', 'f_code', 'path', 'http_status', 'code',
                'method_code'
            ),
            buckets=inner_metrics_buckets
        )

    if requests is not None:
        requests.Session.request = \
            partner_http_metrics(requests.Session.request)
        this.metrics_partner_http = Histogram(
            name='partner_http_metrics',
            documentation='...',
            labelnames=(
                'appid', 'application', 'partner', 'action_code', 'http_status',
                'code'
            ),
            buckets=partner_http_metrics_buckets
        )

    if Consumer is not None:
        Consumer.register_worker = \
            wrap_register_worker(Consumer.register_worker)
        this.metrics_consumer = Histogram(
            name=this.syscode + '_consumer_metrics',
            documentation='...',
            labelnames=('appid', 'application', 'f_code', 'topic', 'code'),
            buckets=consumer_metrics_buckets
        )

    thread = threading.Thread(
        target=start_prometheus_metrics_server,
        args=(default_metrics_port,)
    )
    thread.name = 'StartPrometheusMetricsServer'
    thread.daemon = True
    thread.start()


def start_prometheus_metrics_server(port):
    if Flask is not None:
        start = time.time()
        while time.time() - start < 40:
            if hasattr(Flask, '__running__'):
                return
            time.sleep(.01)
    start_http_server(port)


def inner_metrics_before():
    if request.path in ('/healthcheck', '/metrics') \
            or not hasattr(this, 'syscode'):
        return

    if not hasattr(g, '__request_time__'):
        g.__request_time__ = datetime.now()

    if not hasattr(g, '__request_headers__'):
        g.__request_headers__ = dict(request.headers)

    if not hasattr(g, '__request_data__'):
        if request.args:
            request_data = request.args.to_dict()
        elif request.form:
            request_data = request.form.to_dict()
        else:
            request_body = request.data
            try:
                request_data = json.loads(request_body) \
                    if request_body else None
            except ValueError:
                request_data = None
        g.__request_data__ = request_data


def inner_metrics(response):
    if request.path in ('/healthcheck', '/metrics') \
            or not hasattr(this, 'syscode'):
        return response

    f_code = FuzzyGet(g.__request_headers__, 'User-Agent').v

    if is_char(f_code) and len(f_code) > 20:
        f_code = f_code[:20] + '...'

    method_code = (
        getattr(request, 'method_code', None)
        or FuzzyGet(g.__request_headers__, 'Method-Code').v
        or FuzzyGet(g.__request_data__, 'method_code').v
    )
    try:
        response_data = json.loads(response.get_data())
    except ValueError:
        code = -1
    else:
        code = FuzzyGet(response_data, 'code').v

    this.metrics_inner.labels(
        appid=this.appid,
        application=this.syscode,
        f_code=f_code,
        path=request.path,
        http_status=response.status_code,
        code=code or '',
        method_code=method_code or ''
    ).observe((datetime.now() - g.__request_time__).total_seconds() * 1000)

    return response


def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


def partner_http_metrics(func):

    @functools.wraps(func)
    def inner(self, method, url, *a, **kw):
        request_time = datetime.now()
        response = func(self, method, url, *a, **kw)
        response_time = datetime.now()

        parsed_url = urlparse(url)
        config = xx.get(parsed_url.netloc)

        if config is None:
            return response

        try:
            response_data = response.json()
        except ValueError:
            code = -1
        else:
            code = (
                FuzzyGet(response_data, 'code').v
                or FuzzyGet(response_data, 'errorcode').v
                or -1
            )

        this.metrics_partner_http.labels(
            appid=this.appid,
            application=this.syscode,
            partner=config['partner'],
            action_code=config['paths'].get(parsed_url.path, ''),
            http_status=response.status_code,
            code=code
        ).observe((response_time - request_time).total_seconds() * 1000)

        return response

    inner.__wrapped__ = func
    return inner


def consumer_metrics(func, topic):
    @functools.wraps(func)
    def inner(*a, **kw):
        r = None
        start_time = datetime.now()
        try:
            r = func(*a, **kw)
        finally:
            this.metrics_consumer.labels(
                appid=this.appid,
                application=this.syscode,
                f_code='',
                topic=topic,
                code=0 if r == 0 else 1
            ).observe((datetime.now() - start_time).total_seconds() * 1000)
        return r

    return inner


class FuzzyGet(dict):
    v = None

    def __init__(self, data, key, root=None):
        if root is None:
            self.key = key.replace('-', '').replace('_', '').lower()
            root = self
        for k, v in data.items():
            if k.replace('-', '').replace('_', '').lower() == root.key:
                root.v = data[k]
                break
            dict.__setitem__(self, k, FuzzyGet(v, key=key, root=root))

    def __new__(cls, data, *a, **kw):
        if isinstance(data, dict):
            return dict.__new__(cls)
        if isinstance(data, (list, tuple)):
            return data.__class__(cls(v, *a, **kw) for v in data)
        return cls


xx = {
    'd002.youtu.realname.dzqd.cn:38087': {
        'partner': 1,
        'paths': {
            '/youtu/openliveapi/livedetectonly': 805,
            '/actionliveapi/actionlive': 808,
            '/youtu/openliveapi/livegetfour': 801,
            '/youtu/openliveapi/facecomparewithwatermark': 806,
            '/youtu/api/facecompare': 807,
            '/youtu/openliveapi/get_images_from_video': '',
        }
    },
    'd110.youtu.realname.dzqd.cn:39090': {
        'partner': 1,
        'paths': {
            '/youtu/ocrapi/idcardocr': 802
        }
    },
    'd110.youtu.realname.dzqd.cn:9978': {
        'partner': 1,
        'paths': {
            '/pictureliveapi/facecompare': 807
        }
    },
    'd110.youtu.realname.dzqd.cn:9988': {
        'partner': 1,
        'paths': {
            '/pictureliveapi/picturelivedetect': 804
        }
    },
    'd110.youtu.realname.dzqd.cn:9998': {
        'partner': 1,
        'paths': {
            '/actionliveapi/videoextraimageselect': 811
        }
    },
    'd004.youtu.realname.dzqd.cn:9999': {
        'partner': 1,
        'paths': {
            '/txcFaceid/h5/getToken': 812
        }
    },
    '10.148.247.1:9999': {
        'partner': 1,
        'paths': {
            '/txcFaceid/h5/getToken': 812,
            '/txcFaceid/h5/getToken_new': 812
        }
    },
    'd004.gzt.realname.dzqd.cn:8085': {
        'partner': 2,
        'paths': {
            '/ocr/analyse/p1/front': 401,
            '/ocr/analyse/p1/front/order': 405,
            '/ocr/analyse/p1/back': 402,
            '/ocr/face/p1/hand': 404,
            '/ocr/face/p1/mask': 403,
            '/face/decrypt': 408,
            '/ocr/face/p2/video/verify': 407,
            '/ocr/face/p2/decrypt/verify/images': 406
        }
    },
    'd005.gzt.realname.dzqd.cn:8083': {
        'partner': 2,
        'paths': {
            '/ocr/face/p2/video/verify': 407,
            '/ocr/face/p2/decrypt/verify/images': 406
        }
    },
    'd002.gzt.realname.dzqd.cn:9901': {
        'partner': 2,
        'paths': {
            '/xpcompare': 408
        }
    },
    '10.128.86.64:8000': {
        'partner': '',
        'paths': {
            '/serviceAgent/rest/external/singleIdInfo': 820,
            '/serviceAgent/rest/external/singleIdInfoImg': 820
        }
    },
    '10.130.219.20:31789': {
        'partner': '',
        'paths': {
            '/serviceAgent/rest/fjcrm/post/core/server/checkIdCardBaseFace':
                831,
            '/serviceAgent/rest/fjcrm/post/core/server/checkIdCardBase': ''
        }
    },
    '10.130.219.34:10002': {
        'partner': '',
        'paths': {
            '/core/server/checkIdcardBaseFace': 831,
            '/core/server/checkIdcardBase': ''
        }
    }
}
xx['172.16.50.35:9006'] = xx['d002.youtu.realname.dzqd.cn:38087']
xx['172.16.50.35:39090'] = xx['d110.youtu.realname.dzqd.cn:39090']
xx['172.16.50.35:9978'] = xx['d110.youtu.realname.dzqd.cn:9978']
xx['172.16.50.35:9988'] = xx['d110.youtu.realname.dzqd.cn:9988']
xx['172.16.50.35:9998'] = xx['d110.youtu.realname.dzqd.cn:9998']
xx['172.16.50.35:9999'] = xx['10.148.247.1:9999']
xx['172.16.50.35:28080'] = xx['d004.gzt.realname.dzqd.cn:8085']
xx['172.16.5.9:8083'] = xx['d005.gzt.realname.dzqd.cn:8083']
xx['172.16.50.35:9006']['paths'].update(xx['10.128.86.64:8000']['paths'])
xx['172.16.50.35:9006']['paths'].update(xx['10.130.219.20:31789']['paths'])
xx['172.16.50.35:9006']['paths'].update(xx['10.130.219.34:10002']['paths'])
