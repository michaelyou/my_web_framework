import time
import logging
import db


_triggers = frozenset(['pre_insert', 'pre_update', 'pre_delete'])


def _gen_sql(table_name, mappings):
    pk = None
    sql = ['-- generating SQL for %s:' % table_name, 'create table `%s` (' % table_name]
    for f in sorted(mappings.values(), lambda x, y: cmp(x._order, y._order)):
        if not hasattr(f, 'ddl'):
            raise StandardError('no ddl in field "%s".' % f)
        ddl = f.ddl
        nullable = f.nullable
        if f.primary_key:
            pk = f.name
        sql.append('  `%s` %s,' % (f.name, ddl) if nullable else '  `%s` %s not null,' % (f.name, ddl))
    sql.append('  primary key(`%s`)' % pk)
    sql.append(');')
    return '\n'.join(sql)


class Field(object):

    _count = 0

    def __init__(self, **kwargs):
        self.name = kwargs.get('name', None)
        self._default = kwargs.get('default', None)
        self.primary_key = kwargs.get('primary_key', False)
        self.nullable = kwargs.get('nullable', False)
        self.updatable = kwargs.get('updatable', True)
        self.insertable = kwargs.get('insertable', True)
        self.ddl = kwargs.get('ddl', '')
        self._order = Field._count
        Field._count += 1

    @property
    def default(self):
        d = self._default
        return d() if callable(d) else d


class StringField(Field):

    def __init__(self, **kwargs):
        if 'default' not in kwargs:
            kwargs['default'] = ''
        if 'ddl' not in kwargs:
            kwargs['ddl'] = 'varchar(255)'

        super(StringField, self).__init__(**kwargs)


class IntegerField(Field):

    def __init__(self, **kwargs):
        if 'default' not in kwargs:
            kwargs['default'] = 0
        if 'ddl' not in kwargs:
            kwargs['ddl'] = 'bigint'

        super(IntegerField, self).__init__(**kwargs)


class FloatField(Field):

    def __init__(self, **kwargs):
        if 'default' not in kwargs:
            kwargs['default'] = 0.0
        if 'ddl' not in kwargs:
            kwargs['ddl'] = 'real'

        super(FloatField, self).__init__(**kwargs)


class BooleanField(Field):

    def __init__(self, **kwargs):
        if 'default' not in kwargs:
            kwargs['default'] = False
        if 'ddl' not in kwargs:
            kwargs['ddl'] = 'bool'

        super(BooleanField, self).__init__(**kwargs)


class TextField(Field):

    def __init__(self, **kwargs):
        if 'default' not in kwargs:
            kwargs['default'] = False
        if 'ddl' not in kwargs:
            kwargs['ddl'] = 'text'

        super(TextField, self).__init__(**kwargs)


class ModelMetaClass(type):

    def __new__(cls, name, bases, attrs):
        if name == 'Model':
            return type.__new__(cls, name, bases, attrs)

        if not hasattr(cls, 'subclasses'):
            cls.subclasses = {}
        if name not in cls.subclasses:
            cls.subclasses[name] = name
        else:
            logging.warning('Redefine class: %s' % name)

        logging.info('Scan ORMapping %s...' % name)

        mappings = dict()
        primary_key = None
        for k, v in attrs.iteritems():
            if isinstance(v, Field):
                if not v.name:
                    v.name = k
                logging.info('[MAPPING] Found mapping: %s => %s' % (k, v))
                # check duplicate primary key:
                if v.primary_key:
                    if primary_key:
                        raise TypeError('Cannot define more than 1 primary key in class: %s' % name)
                    if v.updatable:
                        logging.warning('NOTE: change primary key to non-updatable.')
                        v.updatable = False
                    if v.nullable:
                        logging.warning('NOTE: change primary key to non-nullable.')
                        v.nullable = False
                    primary_key = v
                mappings[k] = v

        # check exist of primary key
        if not primary_key:
            raise TypeError('Primary key not defined in class: %s' % name)

        for k in mappings.iterkeys():
            attrs.pop(k)

        if '__table__' not in attrs:
            attrs['__table__'] = name.lower()

        attrs['__mappings__'] = mappings
        attrs['__primary_key__'] = primary_key
        attrs['__sql__'] = _gen_sql(attrs['__table__'], mappings)

        for trigger in _triggers:
            if trigger not in attrs:
                attrs[trigger] = None
        return type.__new__(cls, name, bases, attrs)


class Model(dict):
    __metaclass__ = ModelMetaClass

    def __init__(self, **kwargs):
        super(Model, self).__init__(**kwargs)

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError("'Dict' object has no attribute '%s'" % key)

    def __setattr__(self, key, value):
        self[key] = value

    @classmethod
    def get(cls, pk):
        d = db.select_one('select * from %s where %s=?' % (cls.__table__, cls.__primary_key__.name), pk)
        return cls(**d) if d else None

    def insert(self):
        self.pre_insert and self.pre_insert()
        params = {}
        for k, v in self.__mappings__.iteritems():
            if v.insertable:
                if not hasattr(self, k):
                    setattr(self, k, v.default)
                params[v.name] = getattr(self, k)
        db.insert('%s' % self.__table__, **params)
        return self

    def delete(self):
        self.pre_delete and self.pre_delete()

        pk = self.__primary_key__.name
        args = (getattr(self, pk),)
        db.update('delete from `%s` where `%s`=?' % (self.__table__, pk), *args)
        return self

    @classmethod
    def count_all(cls):
        return db.select('select count(`%s`) from `%s`' % (cls.__primary_key__.name, cls.__table__))


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    db.create_engine('root', 'root123', 'test')

    class User(Model):
        id = IntegerField(primary_key=True)
        name = StringField()
        last_modified = FloatField()

        def pre_insert(self):
            self.last_modified = time.time()

    user = User(id=100, name='youmaimai')
    user.insert()
    print(user.last_modified)
    print(user.__sql__)

    my_user = User.get(100)
    print(my_user)

    my_user.delete()

    count = User.count_all()
    print(count)
