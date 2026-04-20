# coding:utf-8
import os
import re
import sys
import time
import json as jsonx
import warnings
import functools
import traceback
import threading

from datetime import datetime

if os.path.basename(sys.argv[0]) != 'setup.py':
    import prometheus_client


def wrap_api_frame_start_method(api_frame, start_method):
    @functools.wraps(start_method)
    def inner(*a, **kw):
        api_frame.__running__ = True
        start_method(*a, **kw)
    inner.__wrapped__ = start_method
    return inner


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

    Flask.__init__ = wrap_flask_init_method(Flask.__init__)
    Flask.run = wrap_api_frame_start_method(Flask, Flask.run)

try:
    from gevent.baseserver import BaseServer as WSGIServer
except ImportError:
    WSGIServer = None
else:
    WSGIServer.serve_forever = wrap_api_frame_start_method(WSGIServer, WSGIServer.serve_forever)

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
            func(self, consumer_metrics(worker, topic=self.queue))
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

default_buckets = (100, 200, 500, 800, 1000, 1500, 2000, 2500, 3000, 4000, 5000, 6000, 8000)

deprecated = object()


def __init__(
        syscode,
        inner_metrics_buckets=default_buckets,
        partner_http_metrics_buckets=deprecated,
        external_metrics_buckets=None,
        consumer_metrics_buckets=default_buckets,
        default_metrics_port=9166,
):
    if hasattr(this, 'syscode'):
        return

    if re.match(r'[a-zA-Z]\d{9}$', syscode) is None:
        raise ValueError('parameter syscode "%s" is illegal.' % syscode)

    if partner_http_metrics_buckets is not deprecated:
        warnings.warn(
            'parameter "partner_http_metrics_buckets" will be deprecated soon, replaced to "external_metrics_buckets".',
            category=DeprecationWarning, stacklevel=2
        )
        if external_metrics_buckets is None:
            external_metrics_buckets = partner_http_metrics_buckets

    this.syscode = syscode = syscode.upper()
    this.appid = syscode[:4]

    if Flask is not None:
        this.metrics_inner = prometheus_client.Histogram(
            name=syscode + '_inner_metrics',
            documentation='...',
            labelnames=('appid', 'application', 'f_code', 'path', 'http_status', 'code', 'method_code'),
            buckets=inner_metrics_buckets
        )
        thread = threading.Thread(target=start_prometheus_metrics_server, args=(default_metrics_port,))
        thread.name = 'StartPrometheusMetricsServer'
        thread.daemon = True
        thread.start()
    else:
        prometheus_client.start_http_server(int(default_metrics_port))

    if requests is not None:
        requests.Session.request = http_request_metrics(requests.Session.request)
        this.metrics_partner_http = prometheus_client.Histogram(
            name='partner_http_metrics',
            documentation='...',
            labelnames=('appid', 'application', 'partner', 'action_code', 'http_status', 'code'),
            buckets=external_metrics_buckets or default_buckets
        )
        this.external_calls_total = prometheus_client.Counter(
            name='external_calls_total',
            documentation='Total number of external calls',
            labelnames=('call_type', 'tcode', 'method_code', 'status')
        )
        this.external_call_duration_seconds = prometheus_client.Histogram(
            name='external_call_duration_seconds',
            documentation='Duration of external calls in seconds',
            labelnames=('call_type', 'tcode', 'method_code', 'status'),
            buckets=tuple(v * 0.001 for v in external_metrics_buckets or default_buckets)
        )

    if Consumer is not None:
        Consumer.register_worker = wrap_register_worker(Consumer.register_worker)
        this.metrics_consumer = prometheus_client.Histogram(
            name=this.syscode + '_consumer_metrics',
            documentation='...',
            labelnames=('appid', 'application', 'f_code', 'topic', 'code'),
            buckets=consumer_metrics_buckets
        )


def start_prometheus_metrics_server(port):
    start = time.time()
    while time.time() - start < 3:
        if hasattr(Flask, '__running__') or hasattr(WSGIServer, '__running__'):
            return
        time.sleep(.01)
    prometheus_client.start_http_server(int(port))


def inner_metrics_before():
    try:
        if request.path in ('/healthcheck', '/metrics') or not hasattr(this, 'syscode'):
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
                    request_data = jsonx.loads(request_body) if request_body else None
                except ValueError:
                    request_data = None
            g.__request_data__ = request_data
    except Exception:
        sys.stderr.write(
            traceback.format_exc() + '\nAn exception occurred while '
            'recording the metrics.'
        )


def inner_metrics(response):
    try:
        if (
                response.status_code == 404
                or request.path in ('/healthcheck', '/metrics')
                or not hasattr(this, 'syscode')
        ):
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
            response_data = jsonx.loads(response.get_data())
        except ValueError:
            code = -1
        else:
            code = FuzzyGet(response_data, 'code').v
            if code is None:
                code = ''

        this.metrics_inner.labels(
            appid=this.appid,
            application=this.syscode,
            f_code=f_code,
            path=request.path,
            http_status=response.status_code,
            code=code,
            method_code=method_code or ''
        ).observe((datetime.now() - g.__request_time__).total_seconds() * 1000)
    except Exception:
        sys.stderr.write(
            traceback.format_exc() + '\nAn exception occurred while '
            'recording the metrics.'
        )
    finally:
        return response


def metrics():
    return Response(prometheus_client.generate_latest(), mimetype=prometheus_client.CONTENT_TYPE_LATEST)


def http_request_metrics(func):

    @functools.wraps(func)
    def inner(self, method, url, headers=None, params=None, data=None, json=None, **kw):
        request_time = datetime.now()
        response = func(self, method, url, headers=headers, params=params, data=data, json=json, **kw)
        response_time = datetime.now()

        duration = (response_time - request_time).total_seconds()
        print("duration", duration)

        try:
            parsed_url = urlparse(url)
            partner_config = partner_interface_config.get(parsed_url.netloc)

            partner_code = method_code = None

            try:
                response_data = response.json()
            except ValueError:
                code = -1
            else:
                code = fuzzy_get_many(response_data, 'code', 'errorcode')
                if code is None:
                    code = -1

            if partner_config is not None:
                partner_code = partner_config['partner']
                method_code = partner_config['paths'].get(parsed_url.path)
                this.metrics_partner_http.labels(
                    appid=this.appid,
                    application=this.syscode,
                    partner=partner_code,
                    action_code=method_code or '',
                    http_status=response.status_code,
                    code=code
                ).observe(duration * 1000)

            if method_code is None:
                method_code = FuzzyGet([headers, params, data, json], 'Method-Code').v

            tcode = partner_code or get_tcode(parsed_url, headers)
            status = 'success' if response.status_code < 400 and code == 0 else 'error'

            this.external_calls_total.labels(
                call_type='http',
                tcode=tcode or '',
                method_code=method_code or '',
                status=status
            ).inc()

            this.external_call_duration_seconds.labels(
                call_type='http',
                tcode=tcode or '',
                method_code=method_code or '',
                status=status
            ).observe(duration)

        except Exception:
            sys.stderr.write(
                traceback.format_exc() + '\nAn exception occurred while recording the metrics.'
            )
        finally:
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
            if isinstance(data, list):
                data = {'data': data}
            self.key = key.replace('-', '').replace('_', '').lower()
            root = self
        for k, v in data.items():
            if k.replace('-', '').replace('_', '').lower() == root.key:
                root.v = data[k]
                break
            dict.__setitem__(self, k, FuzzyGet(v, key=key, root=root))

    def __new__(cls, data, key, root=None):
        if root is None and isinstance(data, list):
            data = {'data': data}
        if isinstance(data, dict):
            return dict.__new__(cls)
        if isinstance(data, (list, tuple)):
            return data.__class__(cls(v, key, root) for v in data)
        return cls


def fuzzy_get_many(data, *keys):
    for k in keys:
        v = FuzzyGet(data, k).v
        if v is not None:
            return v


def get_tcode(parsed_url, request_headers):
    tcode = FuzzyGet(request_headers, 'T-Code').v
    if tcode is None:
        host_prefix = parsed_url.hostname.split('.')[0]
        tcode = host_prefix if is_syscode(host_prefix) else None
    return tcode and tcode.upper()


def is_syscode(x):
    return len(x) == 10 and x[0].isalpha() and x[1:].isdigit()


partner_interface_config = {
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
partner_interface_config['172.16.50.35:9006'] = partner_interface_config['d002.youtu.realname.dzqd.cn:38087']
partner_interface_config['172.16.50.35:39090'] = partner_interface_config['d110.youtu.realname.dzqd.cn:39090']
partner_interface_config['172.16.50.35:9978'] = partner_interface_config['d110.youtu.realname.dzqd.cn:9978']
partner_interface_config['172.16.50.35:9988'] = partner_interface_config['d110.youtu.realname.dzqd.cn:9988']
partner_interface_config['172.16.50.35:9998'] = partner_interface_config['d110.youtu.realname.dzqd.cn:9998']
partner_interface_config['172.16.50.35:9999'] = partner_interface_config['10.148.247.1:9999']
partner_interface_config['172.16.50.35:28080'] = partner_interface_config['d004.gzt.realname.dzqd.cn:8085']
partner_interface_config['172.16.5.9:8083'] = partner_interface_config['d005.gzt.realname.dzqd.cn:8083']
partner_interface_config['172.16.50.35:9006']['paths'].update(partner_interface_config['10.128.86.64:8000']['paths'])
partner_interface_config['172.16.50.35:9006']['paths'].update(partner_interface_config['10.130.219.20:31789']['paths'])
partner_interface_config['172.16.50.35:9006']['paths'].update(partner_interface_config['10.130.219.34:10002']['paths'])
