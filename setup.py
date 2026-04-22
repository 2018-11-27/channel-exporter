# coding:utf-8
import sys
import codecs
import setuptools

if sys.version_info.major < 3:
    open = codecs.open

setuptools.setup(
    name='channel-exporter',
    version='1.2.1',
    author='Nameless Master',
    author_email='<gqylpy@outlook.com>',
    license='MIT',
    project_urls={
        'Source': 'https://github.com/2018-11-27/channel-exporter'
    },
    description='''
        用于 Python 应用的 Prometheus 指标监控库，支持 Flask、Requests 和消息队列消费
        者的监控指标自动收集。
    '''.strip().replace('\n       ', ''),
    long_description=open('README.md', encoding='utf8').read(),
    long_description_content_type='text/markdown',
    packages=['channel_exporter'],
    python_requires='>=2.7',
    install_requires=['prometheus_client'],
    extras_require={
        'flask': ['Flask>=0.10'],
        'requests': ['requests>=2.19'],
        'ctec-consumer': ['ctec-consumer==0.3.7'],
        'gevent': ['gevent>=1.2.2']
    },
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Natural Language :: Chinese (Simplified)',
        'Natural Language :: English',
        'Operating System :: OS Independent',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: Artistic Software',
        'Topic :: Scientific/Engineering :: Mathematics',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Programming Language :: Python :: 3.13',
        'Programming Language :: Python :: 3.14'
    ]
)
