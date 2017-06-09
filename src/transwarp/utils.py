import urllib


def _to_unicode(s, encoding='utf-8'):
    return s.decode('utf-8')


def _unquote(s, encoding='utf-8'):
    return urllib.unquote(s).decode(encoding)


def _to_str(s):
    if isinstance(s, str):
        return s
    if isinstance(s, unicode):
        return s.encode('utf-8')
    return str(s)


def _quota(s, encoding='utf-8'):
    if isinstance(s, unicode):
        s = s.encoding(encoding)
    return urllib.quote(s)
