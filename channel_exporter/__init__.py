# coding:utf-8
from typing import Optional


def __init__(
        syscode,                        # type: str
        inner_metrics_buckets   =None,  # type: Optional[tuple[int, ...]]
        external_metrics_buckets=None,  # type: Optional[tuple[int, ...]]
        consumer_metrics_buckets=None,  # type: Optional[tuple[int, ...]]
        default_metrics_port    =None   # type: Optional[int]
):
    """
    初始化监控配置。

    @param syscode:
        系统服务编码，格式为大写首字母 + 9位数字，例如 "A123010101"。该编码用于生成指标前
        缀和标识应用身份。

    @param inner_metrics_buckets:
        Web 服务内部指标直方图桶配置，单位毫秒。默认为 [100, 200, 500, 800, 1000,
        1500, 2000, 2500, 3000, 4000, 5000, 6000, 8000]。需按升序排列，用于统计请求
        耗时分位分布。

    @param external_metrics_buckets:
        外部接口调用指标直方图桶配置，单位毫秒。默认值同参数 `inner_metrics_buckets`，
        用于统计外部接口和第三方接口调用耗时分位分布。

    @param consumer_metrics_buckets:
        消息队列消费者指标直方图桶配置，单位毫秒。默认值同参数 `inner_metrics_buckets`，
        用于统计消息处理耗时分位分布。

    @param default_metrics_port:
        Prometheus metrics 端点暴露端口，默认为 9166。如果启动了 Flask 服务器，则使用
        Flask 服务器端点。如果你的运行环境安装了 Flask 库但未使用或启动它，默认端点将在延
        迟 40 秒后静默启动。
    """


class _xe6_xad_x8c_xe7_x90_xaa_xe6_x80_xa1_xe7_x8e_xb2_xe8_x90_x8d_xe4_xba_x91:
    import sys

    ipath = __name__ + '.i ' + __name__
    __import__(ipath)

    ipack = sys.modules[__name__]
    icode = globals()['i ' + __name__]

    for iname in globals():
        if iname[0] != '_':
            ifunc = getattr(icode, iname, None)
            if ifunc:
                ifunc.__module__ = __package__
                ifunc.__doc__ = getattr(ipack, iname).__doc__
                setattr(ipack, iname, ifunc)

    ipack.__init__ = icode.__init__
