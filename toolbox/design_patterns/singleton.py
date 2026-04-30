#!/usr/bin/python3
# -*- coding: utf-8 -*-
import inspect


class ParamsSingleton(object):
    """根据传入的参数不同而创建单例.
    由于参数中可能包含字典, 如果转字符串的话, 字典的 key 是无序的.
    所以用了列表而不是字典来存实例. """
    __instance = list()
    _initialized = False

    def __new__(cls, *args, **kwargs):
        kwargs = cls.to_kwargs(*args, **kwargs)
        kwargs['cls'] = cls

        for obj, params in cls.__instance:
            if params == kwargs:
                return obj

        obj = super().__new__(cls)
        # 让每个类实例, 可以拿到自己的 kwargs
        # setattr(obj, 'kwargs', kwargs)
        obj.kwargs = kwargs
        cls.__instance.append((obj, kwargs))
        return obj

    @classmethod
    def get_all_instance(cls) -> list:
        return cls.__instance

    @classmethod
    def to_kwargs(cls, *args, **kwargs):
        """将传入 __init__ 的参数全部转为 key-value 字典的关键字参数"""

        # 获取当前传入参数值.
        argvalues = inspect.getargvalues(inspect.currentframe())
        args = list(argvalues.locals['args'])
        kwargs = argvalues.locals['kwargs']
        for k, v in argvalues.locals.items():
            if k in ('cls', 'args', 'kwargs'):
                continue
            else:
                kwargs[k] = v

        # 获取函数接受哪些参数.
        fullargspec = inspect.getfullargspec(cls.__init__)
        # 函数的参数分为已知的位置参数, 未知的位置参数, 已知的关键字参数, 未知的关键字参数.
        # 在 `未知的位置参数` 之前的参数都是 `已知的位置参数`. 它们可能有默认值
        # 有默认值的参数并不都是关键字参数. 关键字参数也可以没有默认值.

        # fullargspec.args: `已知的位置参数` 的名称的列表.
        # fullargspec.defaults: 元组或None. `已知的位置参数` 中最后几项的默认值.
        # fullargspec.kwonlyargs: `已知的关键字参数` 的名称列表 (没有默认值的关键字参数, 是必须要传入的).
        # fullargspec.kwonlydefaults: `已知的关键字参数` 的默认值.

        arg_name_list = fullargspec.args

        # 将未被赋值 `已知的位置参数` 的默认值写入 kwargs.
        if fullargspec.defaults is not None:
            l = len(fullargspec.defaults)
            default_args = fullargspec.args[-l:]
            for k, v in zip(default_args, fullargspec.defaults):
                if k in kwargs:
                    continue
                else:
                    kwargs[k] = v

        # 将 `已知关键字参数` 的默认值写入 kwargs.
        if fullargspec.kwonlydefaults is not None:
            for k, v in fullargspec.kwonlydefaults.items():
                if k in kwargs:
                    continue
                else:
                    kwargs[k] = v

        # if fullargspec.kwonlyargs is not None:
        #     arg_name_list.extend(fullargspec.kwonlyargs)
                kwargs = dict()
        for arg_name in arg_name_list:
            if arg_name == 'self':
                continue
            try:
                value = args.pop(0)
            except IndexError:
                break
            kwargs[arg_name] = value

        if fullargspec.varargs is not None:
            kwargs[fullargspec.varargs] = tuple(args)

        return kwargs

    @classmethod
    def flush(cls):
        cls.__instance = list()
        return


def demo1():
    class A(ParamsSingleton):
        pass

    class B(A):
        # def __init__(self, name, *args1, age, **kwargs):
        def __init__(self, name, age=27, **kwargs):

            pass

    b1 = B('jack')
    print('-' * 25)
    # b2 = B('jack', 1, 2, age=25, **{'high': 165})
    # print('-' * 25)
    b3 = B(name='jack', **{'age': 25, 'high': 165})
    # b3 = B(name='jack', **{'high': 165})

    print('-' * 25)

    # print(b1)
    return


if __name__ == '__main__':
    demo1()
