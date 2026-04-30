#!/usr/bin/python3
# -*- coding: utf-8 -*-
import logging
import inspect
import typing

from toolbox.porter.common.registrable import Registrable

logger = logging.getLogger("toolbox")


class Params(Registrable):
    """
    仿照 AllenNLP 框架, Params 与 Registrable 配合使用, 通过子类的 Annotation 类型标注使得子类可以通过

    .from_json({
        **parameters
    })

    方式实例化.

    注意事项:
    1. 子类除了 self, 每个参数都必须有类型标注.
    2. 当子类没有 __init__ 方法时, 会调用到基类的该方法 (基类的默认实现没有类型标注),
    因此, 都应实现 __init__ 方法.

    """
    # def __init__(self):
    #     # Subclasses should override this method, even if it is def __init__(self): pass
    #     pass

    @classmethod
    def from_json(cls, params: dict = None, global_params: dict = None):
        """
        :param params:
        :param global_params: 当缺少某参数时, 尝试从 global_params 中查找.
        :return:
        """
        if params is None:
            params = dict()
        if global_params is None:
            global_params = dict()

        if "type" in params:
            cls = cls.by_name(params["type"])

        signature = inspect.signature(cls.__init__)

        kwargs = dict()
        for k, v in signature.parameters.items():
            if k in ("self",):
                continue
            if k in ("args", "kwargs"):
                msg = (
                    f"parameter: args or kwargs is not expected. "
                    f"you may need to override the __init__ method of cls: {cls.__name__}."
                )
                logger.warning(msg)
                print(msg)
                continue

            if v.annotation is inspect._empty:
                raise NotImplementedError(
                    "all parameter should have a annotation. "
                    "parameter `{}` of {} have not annotation".format(k, cls)
                )

            if v.name in params:
                sub_params = params[v.name]
            elif v.name in global_params:
                sub_params = global_params[v.name]
            else:
                continue

            if isinstance(v.annotation, str):
                raise NotImplementedError("string annotation not supported.")

            if hasattr(v.annotation, "_subs_tree"):
                # typing 标注类型.
                subs_tree = v.annotation._subs_tree()
                kwargs[v.name] = cls.from_annotation(sub_params, global_params, subs_tree)
            elif isinstance(v.annotation, typing._GenericAlias):
                # typing 标注类型.
                subs_tree = (v.annotation.__origin__, *v.annotation.__args__)
                kwargs[v.name] = cls.from_annotation(sub_params, global_params, subs_tree)
            elif issubclass(v.annotation, Params):
                # Params 子类.
                kwargs[v.name] = v.annotation.from_json(
                    sub_params, global_params
                )
            elif isinstance(sub_params, v.annotation):
                # 传入的是已实例化好的值.
                kwargs[v.name] = sub_params
            else:
                # str, int, list, dict 等基本类型.
                value = sub_params
                if isinstance(value, dict):
                    value = v.annotation(**value)
                else:
                    value = v.annotation(value)

                kwargs[v.name] = value

        obj = cls.__new__(cls, **kwargs)
        try:
            obj.__init__(**kwargs)
        except TypeError as e:
            print(e)
            print("cls: {}, obj: {}, kwargs: {}".format(cls, obj, kwargs))
            logger.error(e)
            logger.error("cls: {}, obj: {}, kwargs: {}".format(cls, obj, kwargs))
            raise e

        return obj

    @classmethod
    def from_annotation(cls, params, global_params: dict, subs_tree=None):
        if params is None:
            return params
        if subs_tree is None:
            return params

        if isinstance(subs_tree, tuple) and len(subs_tree) > 1:
            # such as: (Dict, str, int) in List[Dict[str, int]]
            args_type = subs_tree[0]
            annotation = subs_tree[1:]
        elif isinstance(subs_tree, tuple) and len(subs_tree) == 1:
            args_type = subs_tree[0]
            annotation = None
        else:
            args_type = subs_tree
            annotation = None

        if args_type is typing.List or args_type is list:
            result = list()
            for param in params:
                result.append(cls.from_annotation(param, global_params, annotation))
            return result
        elif args_type is typing.Dict or args_type is list:
            result = dict()
            for k, v in params.items():
                key = cls.from_annotation(k, global_params, annotation[0])
                value = cls.from_annotation(v, global_params, annotation[1])
                result[key] = value
            return result
        elif args_type is typing.Tuple or args_type is tuple:
            if len(annotation) != len(params):
                raise AssertionError(
                    "number of params not match the annotation. "
                    "{}, annotation: {}, params: {}".format(cls, annotation, params)
                )
            result = list()
            for param, sub_annotation in zip(params, annotation):
                result.append(cls.from_annotation(param, global_params, sub_annotation))
            return tuple(result)
        elif args_type is typing.Union:
            for option in annotation:
                try:
                    result = cls.from_annotation(params, global_params, option)
                    break
                except Exception:
                    continue
            else:
                raise ValueError("no type of Union match the params {}".format(params))
            return result
        elif args_type is typing.Any:
            result = params
            return result

        if hasattr(typing, "GenericMeta"):
            built_in_type = typing.GenericMeta
        elif hasattr(typing, "GenericAlias"):
            built_in_type = typing.GenericAlias
        else:
            raise NotImplementedError

        if not isinstance(args_type, built_in_type):
            if hasattr(args_type, "from_json"):
                result = args_type.from_json(params, global_params)
            elif isinstance(args_type, tuple) and len(args_type) > 0 and isinstance(args_type[0], built_in_type):
                # List[Dict[str, List[str]]]
                result = cls.from_annotation(params, global_params, args_type)
            else:
                if isinstance(params, dict):
                    result = args_type(**params)
                else:
                    result = args_type(params)

            return result

        raise NotImplementedError(
            "{}, params: {}, subs_tree: {}".format(cls, params, subs_tree)
        )


if __name__ == "__main__":
    pass
