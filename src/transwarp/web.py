# encoding=utf-8
import re
import types
import urllib
import cgi
import datetime
import logging
import threading
from wsgiref.simple_server import make_server

import utils
from db import Dict


_RESPONSE_STATUSES = {
    # Informational
    100: 'Continue',
    101: 'Switching Protocols',
    102: 'Processing',

    # Successful
    200: 'OK',
    201: 'Created',
    202: 'Accepted',
    203: 'Non-Authoritative Information',
    204: 'No Content',
    205: 'Reset Content',
    206: 'Partial Content',
    207: 'Multi Status',
    226: 'IM Used',

    # Redirection
    300: 'Multiple Choices',
    301: 'Moved Permanently',
    302: 'Found',
    303: 'See Other',
    304: 'Not Modified',
    305: 'Use Proxy',
    307: 'Temporary Redirect',

    # Client Error
    400: 'Bad Request',
    401: 'Unauthorized',
    402: 'Payment Required',
    403: 'Forbidden',
    404: 'Not Found',
    405: 'Method Not Allowed',
    406: 'Not Acceptable',
    407: 'Proxy Authentication Required',
    408: 'Request Timeout',
    409: 'Conflict',
    410: 'Gone',
    411: 'Length Required',
    412: 'Precondition Failed',
    413: 'Request Entity Too Large',
    414: 'Request URI Too Long',
    415: 'Unsupported Media Type',
    416: 'Requested Range Not Satisfiable',
    417: 'Expectation Failed',
    418: "I'm a teapot",
    422: 'Unprocessable Entity',
    423: 'Locked',
    424: 'Failed Dependency',
    426: 'Upgrade Required',

    # Server Error
    500: 'Internal Server Error',
    501: 'Not Implemented',
    502: 'Bad Gateway',
    503: 'Service Unavailable',
    504: 'Gateway Timeout',
    505: 'HTTP Version Not Supported',
    507: 'Insufficient Storage',
    510: 'Not Extended',
}

_RESPONSE_HEADERS = (
    'Accept-Ranges',
    'Age',
    'Allow',
    'Cache-Control',
    'Connection',
    'Content-Encoding',
    'Content-Language',
    'Content-Length',
    'Content-Location',
    'Content-MD5',
    'Content-Disposition',
    'Content-Range',
    'Content-Type',
    'Date',
    'ETag',
    'Expires',
    'Last-Modified',
    'Link',
    'Location',
    'P3P',
    'Pragma',
    'Proxy-Authenticate',
    'Refresh',
    'Retry-After',
    'Server',
    'Set-Cookie',
    'Strict-Transport-Security',
    'Trailer',
    'Transfer-Encoding',
    'Vary',
    'Via',
    'Warning',
    'WWW-Authenticate',
    'X-Frame-Options',
    'X-XSS-Protection',
    'X-Content-Type-Options',
    'X-Forwarded-Proto',
    'X-Powered-By',
    'X-UA-Compatible',
)
_RESPONSE_HEADER_DICT = dict(zip(map(lambda x: x.upper(), _RESPONSE_HEADERS), _RESPONSE_HEADERS))

_RE_RESPONSE_STATUS = re.compile(r'^\d\d\d(\ [\w\ ]+)?$')

_HEADER_X_POWERED_BY = ('X-Powered-By', 'transwarp/1.0')
_RE_TZ = re.compile('^([\+\-])([0-9]{1,2})\:([0-9]{1,2})$')
_TIMEDELTA_ZERO = datetime.timedelta(0)
ctx = threading.local()


# 用于异常处理
class _HttpError(Exception):

    def __init__(self, code):
        """
        Init an HttpError with response code.
        """
        super(_HttpError, self).__init__()
        self.status = '%d %s' % (code, _RESPONSE_STATUSES[code])
        self._headers = None

    def header(self, name, value):
        """
        添加header， 如果header为空则 添加powered by header
        """
        if not self._headers:
            self._headers = [_HEADER_X_POWERED_BY]
        self._headers.append((name, value))

    @property
    def headers(self):
        """
        使用setter方法实现的 header属性
        """
        if hasattr(self, '_headers'):
            return self._headers
        return []

    def __str__(self):
        return self.status

    __repr__ = __str__


class _RedirectError(_HttpError):

    """
    RedirectError that defines http redirect code.
    >>> e = _RedirectError(302, 'http://www.apple.com/')
    >>> e.status
    '302 Found'
    >>> e.location
    'http://www.apple.com/'
    """

    def __init__(self, code, location):
        """
        Init an HttpError with response code.
        """
        super(_RedirectError, self).__init__(code)
        self.location = location

    def __str__(self):
        return '%s, %s' % (self.status, self.location)

    __repr__ = __str__


class _URLNotFoundError(_HttpError):

    def __init__(self, code=404):
        super(_URLNotFoundError, self).__init__(code)

    def __str__(self):
        return 'url not found'

    __repr__ = __str__


class HttpError(object):

    """
    HTTP Exceptions
    """
    @staticmethod
    def badrequest():
        """
        Send a bad request response.
        >>> raise HttpError.badrequest()
        Traceback (most recent call last):
          ...
        _HttpError: 400 Bad Request
        """
        return _HttpError(400)

    @staticmethod
    def unauthorized():
        """
        Send an unauthorized response.
        >>> raise HttpError.unauthorized()
        Traceback (most recent call last):
          ...
        _HttpError: 401 Unauthorized
        """
        return _HttpError(401)

    @staticmethod
    def forbidden():
        """
        Send a forbidden response.
        >>> raise HttpError.forbidden()
        Traceback (most recent call last):
          ...
        _HttpError: 403 Forbidden
        """
        return _HttpError(403)

    @staticmethod
    def notfound():
        """
        Send a not found response.
        >>> raise HttpError.notfound()
        Traceback (most recent call last):
          ...
        _HttpError: 404 Not Found
        """
        return _HttpError(404)

    @staticmethod
    def conflict():
        """
        Send a conflict response.
        >>> raise HttpError.conflict()
        Traceback (most recent call last):
          ...
        _HttpError: 409 Conflict
        """
        return _HttpError(409)

    @staticmethod
    def internalerror():
        """
        Send an internal error response.
        >>> raise HttpError.internalerror()
        Traceback (most recent call last):
          ...
        _HttpError: 500 Internal Server Error
        """
        return _HttpError(500)

    @staticmethod
    def redirect(location):
        """
        Do permanent redirect.
        >>> raise HttpError.redirect('http://www.itranswarp.com/')
        Traceback (most recent call last):
          ...
        _RedirectError: 301 Moved Permanently, http://www.itranswarp.com/
        """
        return _RedirectError(301, location)

    @staticmethod
    def found(location):
        """
        Do temporary redirect.
        >>> raise HttpError.found('http://www.itranswarp.com/')
        Traceback (most recent call last):
          ...
        _RedirectError: 302 Found, http://www.itranswarp.com/
        """
        return _RedirectError(302, location)

    @staticmethod
    def seeother(location):
        """
        Do temporary redirect.
        >>> raise HttpError.seeother('http://www.itranswarp.com/')
        Traceback (most recent call last):
          ...
        _RedirectError: 303 See Other, http://www.itranswarp.com/
        >>> e = HttpError.seeother('http://www.itranswarp.com/seeother?r=123')
        >>> e.location
        'http://www.itranswarp.com/seeother?r=123'
        """
        return _RedirectError(303, location)


class UTC(datetime.tzinfo):

    def __init__(self, utc):
        utc = str(utc.strip().upper())
        mt = _RE_TZ.match(utc)
        if mt:
            minus = mt.group(1) == '-'
            h = int(mt.group(2))
            m = int(mt.group(3))
            if minus:
                h, m = (-h), (-m)
            self._utcoffset = datetime.timedelta(hours=h, minutes=m)
            self._tzname = 'UTC%s' % utc
        else:
            raise ValueError('bad utc time zone')

    def utcoffset(self, dt):
        """
        表示与标准时区的 偏移量
        """
        return self._utcoffset

    def dst(self, dt):
        """
        Daylight Saving Time 夏令时
        """
        return _TIMEDELTA_ZERO

    def tzname(self, dt):
        """
        所在时区的名字
        """
        return self._tzname

    def __str__(self):
        return 'UTC timezone info object (%s)' % self._tzname

    __repr__ = __str__

UTC_0 = UTC('+00:00')


class MultipartFile(object):

    def __init__(self, storage):
        self.filename = utils.to_unicode(storage.filename)
        self.file = storage.file


class Request(object):

    def __init__(self, environ):
        self._environ = environ

    def _parse_input(self):

        def _convert(item):
            if isinstance(item, list):
                return [utils.to_unicode(i.value) for i in item]
            if item.filename:
                return MultipartFile(item)
            # return utils.to_unicode(item.value)
            return item.value

        print('environ', self._environ)
        fs = cgi.FieldStorage(fp=self._environ['wsgi.input'], environ=self._environ, keep_blank_values=True)
        inputs = dict()
        for key in fs:
            inputs[key] = _convert(fs[key])
        return inputs

    def _get_raw_input(self):
        if not hasattr(self, '_raw_input'):
            self._raw_input = self._parse_input()
        return self._raw_input

    def __getitem__(self, key):
        r = self._get_raw_input()[key]
        # i think this is not good, it means you can't pass list to the server
        if isinstance(r, list):
            return r[0]
        return r

    def get(self, key):
        print('after parse', self._get_raw_input())
        r = self._get_raw_input()[key]
        if isinstance(r, list):
            return r[0]
        return r

    def get_list(self, key):
        r = self._get_raw_input()[key]
        if isinstance(r, list):
            return r[:]
        return [r]

    def input(self, **kwargs):
        copy = Dict(**kwargs)
        raw = self._get_raw_input()
        for k, v in raw.iteritems():
            copy[k] = v[0] if isinstance(v, list) else v
        return copy

    def get_body(self):
        fp = self._environ('wsgi.input')
        return fp.read()

    @property
    def remote_addr(self):
        return self._environ.get('REMOTE_ADDR')

    @property
    def query_string(self):
        return self._environ.get('QUERY_STRING', '')

    @property
    def environ(self):
        return self._environ

    @property
    def request_method(self):
        return self._environ.get('REQUEST_METHOD')

    @property
    def path_info(self):
        return urllib.unquote(self._environ.get('PATH_INFO', ''))

    @property
    def host(self):
        return self._environ.get('HTTP_HOST', '')

    @property
    def _get_headers(self):
        if not hasattr(self, '_headers'):
            headers = {}
            for k, v in self._environ.iteritems():
                if k.startswith('HTTP_'):
                    # this is important
                    headers[k[5:].repace('_', '-').upper()] = v.decode('utf-8')
            self._headers = headers
        return self._headers

    @property
    def headers(self):
        return dict(**self._get_headers())

    @property
    def header(self, header, default=None):
        return self._get_headers().get(header.upper(), default)

    @property
    def _get_cookies(self):
        if not hasattr(self, '_cookies'):
            cookies = {}
            cookie_str = self._environ.get('HTTP_COOKIE')
            if cookie_str:
                for c in cookie_str.split(';'):
                    pos = c.find('=')
                    if pos > 0:
                        cookies[c[:pos].strip()] = utils.unquote(c[pos+1:])
            self._cookies = cookies
        return self._cookies

    @property
    def cookies(self):
        return Dict(**self._get_cookies())

    @property
    def cookie(self, name, default=None):
        return self._get_cookies().get(name, default)


class Response(object):

    def __init__(self):
        self._status = '200 OK'
        self._headers = {'CONTENT-TYPE': 'text/html; charset=utf-8'}

    def unset_header(self, name):
        key = name.upper()
        if key not in _RESPONSE_HEADER_DICT:
            key = name
        if key in self._headers:
            del self._headers[key]

    def set_header(self, name, value):
        key = name.upper()
        if key not in _RESPONSE_HEADER_DICT:
            key = name
        self._headers[key] = utils._to_str(value)

    def header(self, name):
        key = name.upper()
        if key not in _RESPONSE_HEADER_DICT:
            key = name
        return self._headers.get(key)

    @property
    def headers(self):
        L = [(_RESPONSE_HEADER_DICT.get(k, k), v) for k, v in self._headers.iteritems()]
        if hasattr(self, '_cookies'):
            for v in self._cookies.itervalues():
                L.append(('Set-Cookie'), v)
        L.append(_HEADER_X_POWERED_BY)
        return L

    @property
    def content_type(self):
        return self.header('CONTENT_TYPE')

    @content_type.setter
    def content_type(self, value):
        if value:
            self.set_header('CONTENT_TYPE', value)
        else:
            self.unset_header('CONTENT-TYPE')

    @property
    def content_length(self):
        return self.header('CONTENT-LENGTH')

    @content_length.setter
    def content_length(self, value):
        self.set_header('CONTENT-LENGTH', str(value))

    def delete_cookie(self, name):
        self.set_cookie(name, '__deleted__', expires=0)

    def set_cookie(self, name, value, max_age=None, expires=None, path='/', domain=None, secure=False, http_only=True):
        if not hasattr(self, '_cookies'):
            self._cookies = {}
        L = ['%s=%s' % (utils.quote(name), utils._quote(value))]
        if expires is not None:
            if isinstance(expires, (float, int, long)):
                L.append('Expires=%s' % datetime.datetime.fromtimestamp(expires, UTC_0).strftime('%a, %d-%b-%Y %H:%M:%S GMT'))
            elif isinstance(expires, (datetime.date, datetime.datetime)):
                L.append('Expires=%s' % expires.astimezone(UTC_0).strftime('%a, %d-%b-%Y %H:%M:%S GMT'))
        elif isinstance(max_age, (int, long)):
            L.append('Max-Age=%d' % max_age)
        L.append('Path=%s' % path)
        if domain:
            L.append('Domain=%s' % domain)
        if secure:
            L.append('Secure')
        if http_only:
            L.append('HttpOnly')
        self._cookies[name] = '; '.join(L)

    def unset_cookie(self, name):
        if hasattr(self, '_cookies'):
            if name in self._cookies:
                del self._cookies[name]

    @property
    def status_code(self):
        return int(self._status[:3])

    @property
    def status(self):
        return self._status

    @status.setter
    def status(self, value):
        if isinstance(value, (int, long)):
            if 100 <= value <= 900:
                st = _RESPONSE_STATUSES.get(value, '')
                if st:
                    self._status = "%d %s" % (value, st)
                else:
                    self.status = value
            else:
                raise ValueError('Bad response code: %d' % value)
        elif isinstance(value, basestring):
            if isinstance(value, unicode):
                value = value.encode('utf-8')
            if _RE_RESPONSE_STATUS.match(value):
                self._status = value
            else:
                raise ValueError('Bad response code: %s' % value)
        else:
            raise TypeError('Bad type of response code.')


_re_route = re.compile(r'(:[a-zA-Z_]\w*)')


def get(path):

    def _decorator(func):
        func.__web_route__ = path
        func.__web_method__ = 'GET'
        return func
    return _decorator


def post(path):

    def _decorator(func):
        func.__web_route__ = path
        func.__web_method__ = 'POST'
        return func
    return _decorator


def _build_regex(path):
    # 用于将路径转换成正则表达式，并捕获其中的参数
    re_list = ['^']
    var_list = []
    is_var = False
    for v in _re_route.split(path):
        if is_var:
            var_name = v[1:]
            var_list.append(var_name)
            re_list.append(r'(?P<%s>[^\/]+)' % var_name)
        else:
            s = ''
            for ch in v:
                if '0' <= ch <= '9':
                    s += ch
                elif 'A' <= ch <= 'Z':
                    s += ch
                elif 'a' <= ch <= 'z':
                    s += ch
                else:
                    s = s + '\\' + ch
            re_list.append(s)
        is_var = not is_var
    re_list.append('$')
    return ''.join(re_list)


class Route(object):

    def __init__(self, func):
        self.path = func.__web_route__
        self.method = func.__web_method__
        self.is_static = _re_route.search(self.path) is None
        if not self.is_static:
            self.route = re.compile(_build_regex(self.path))
        self.func = func

    def match(self, url):

        m = self.route.match(url)
        if m:
            return m.groups()
        return None

    def __call__(self, *args):
        return self.func(*args)

    def __str__(self):
        if self.is_static:
            return 'Route(static,%s,path=%s)' % (self.method, self.path)
        return 'Route(dynamic,%s,path=%s)' % (self.method, self.path)

    __repr__ = __str__


def _build_interceptor_fn(func, next):
    """
    拦截器接受一个next函数，这样，一个拦截器可以决定调用next()继续处理请求还是直接返回
    """

    def _wrapper():
        if func.__interceptor__(ctx.request.path_info):
            return func(next)
        else:
            return next()
    return _wrapper


def _build_interceptor_chain(last_fn, *interceptors):
    """
    Build interceptor chain.
    >>> def target():
    ...     print 'target'
    ...     return 123
    >>> @interceptor('/')
    ... def f1(next):
    ...     print 'before f1()'
    ...     return next()
    >>> @interceptor('/test/')
    ... def f2(next):
    ...     print 'before f2()'
    ...     try:
    ...         return next()
    ...     finally:
    ...         print 'after f2()'
    >>> @interceptor('/')
    ... def f3(next):
    ...     print 'before f3()'
    ...     try:
    ...         return next()
    ...     finally:
    ...         print 'after f3()'
    >>> chain = _build_interceptor_chain(target, f1, f2, f3)
    >>> ctx.request = Dict(path_info='/test/abc')
    >>> chain()
    before f1()
    before f2()
    before f3()
    target
    after f3()
    after f2()
    123
    >>> ctx.request = Dict(path_info='/api/')
    >>> chain()
    before f1()
    before f3()
    target
    after f3()
    123
    """
    L = list(interceptors)
    L.reverse()
    fn = last_fn
    for f in L:
        fn = _build_interceptor_fn(f, fn)
    return fn


def _load_module(module_name):
    last_dot = module_name.rfind('.')
    # not found
    if last_dot == -1:
        return __import__(module_name, globals(), locals())
    from_module = module_name[:last_dot]
    import_module = module_name[last_dot+1:]
    m = __import__(from_module, globals(), locals(), [import_module])
    return getattr(m, import_module)


class WSGIApplication(object):

    def __init__(self, document_root=None, **kwargs):
        self._running = False
        self._document_root = document_root

        self._interceptors = []

        self._get_static = {}
        self._post_static = {}

        self._get_dynamic = []
        self._post_dynamic = []

    def _check_not_running(self):
        if self._running:
            raise RuntimeError('Cannot modify WSGIApplication when running.')

    def add_module(self, module):
        self._check_not_running()
        m = module if isinstance(module, types.ModuleType) else _load_module(module)
        logging.info('Add module: %s' % m.__name__)
        for name in dir(m):
            fn = getattr(m, name)
            if callable(fn) and hasattr(fn, '__web_route__') and hasattr(fn, '__web_method__'):
                self.add_url(fn)

    def add_url(self, func):
        self._check_not_running()
        route = Route(func)
        if route.is_static:
            if route.method == 'GET':
                self._get_static[route.path] = route
            elif route.method == 'POST':
                self._post_static[route.path] = route
        else:
            if route.method == 'GET':
                self._get_dynamic.append(route)
            elif route.method == 'POST':
                self._post_dynamic.append(route)
        logging.info('Add route: %s' % str(route))

    def run(self, port=9000, host='127.0.0.1'):
        """
        启动python自带的WSGI Server
        """
        logging.info('application (%s) will start at %s:%s...' % (self._document_root, host, port))
        server = make_server(host, port, self.get_wsgi_application(debug=True))
        server.serve_forever()

    def get_wsgi_application(self, debug=False):
        self._check_not_running()
        # if debug:
        #     self._get_dynamic.append(StaticFileRoute())
        self._running = True

        # {'document_root': '/Users/**/code/my_web_framework/src'}
        _application = Dict(document_root=self._document_root)

        def fn_route():
            request_method = ctx.request.request_method
            path_info = ctx.request.path_info
            if request_method == 'GET':
                fn = self._get_static.get(path_info)
                if fn:
                    return fn()
                for fn in self._get_dynamic:
                    args = fn.match(path_info)
                    if args:
                        return fn(*args)
                raise _URLNotFoundError
            if request_method == 'POST':
                fn = self._post_static.get(path_info)
                if fn:
                    return fn()
                for fn in self._post_dynamic:
                    args = fn.match(path_info)
                    if args:
                        return fn(*args)
                raise _URLNotFoundError

        fn_exec = _build_interceptor_chain(fn_route, *self._interceptors)

        def wsgi(env, start_response):
            # WSGI 处理函数
            ctx.application = _application
            ctx.request = Request(env)
            response = ctx.response = Response()
            try:
                r = fn_exec()
                if isinstance(r, unicode):
                    r = r.encode('utf-8')
                if r is None:
                    r = []
                start_response(response.status, response.headers)
                return r
            except _RedirectError, e:
                response.set_header('Location', e.location)
                start_response(e.status, response.headers)
                return []
            except _URLNotFoundError as e:
                start_response(e.status, response.headers)
                return []
            except Exception as e:
                return []
            finally:
                del ctx.application
                del ctx.request
                del ctx.response

        return wsgi
