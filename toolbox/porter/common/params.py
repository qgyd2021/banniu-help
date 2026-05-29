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
            if k == "self":
                continue
            if k in ("args", "kwargs"):
                msg = (
                    f"parameter: args or kwargs is not expected. "
                    f"you may need to override the __init__ method of cls: {cls.__name__}."
                )
                logger.warning(msg)
                # print(msg)
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

            kwargs[v.name] = cls.from_annotation(sub_params, global_params, v.annotation)

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
    def from_annotation(cls, params, global_params: dict, annotation=None):
        """递归把 JSON 原值按 ``annotation`` 标注的类型还原。

        使用 ``typing.get_origin`` / ``typing.get_args`` 规范处理嵌套泛型，
        避免依赖 ``typing._GenericAlias`` / ``_subs_tree`` 这类私有 / 旧版 API；
        在 3.9+/3.12 上能正确解析 ``List[Tuple[str, str, str]]``、
        ``Dict[str, List[str]]``、``Optional[X]`` 等组合。
        """
        if annotation is None:
            return params

        if annotation is typing.Any:
            return params

        origin = typing.get_origin(annotation)
        args = typing.get_args(annotation)

        # List[X] / list[X]
        if origin in (list, typing.List):
            if params is None:
                return None
            sub = args[0] if args else None
            return [cls.from_annotation(p, global_params, sub) for p in params]

        # Dict[K, V] / dict[K, V]
        if origin in (dict, typing.Dict):
            if params is None:
                return None
            k_anno = args[0] if len(args) >= 1 else None
            v_anno = args[1] if len(args) >= 2 else None
            return {
                cls.from_annotation(k, global_params, k_anno): cls.from_annotation(v, global_params, v_anno)
                for k, v in params.items()
            }

        # Tuple[A, B, C] / tuple[A, B, C]；要求长度严格一致（不处理 Tuple[X, ...] 变长形式）
        if origin in (tuple, typing.Tuple):
            if params is None:
                return None
            if len(args) != len(params):
                raise AssertionError(
                    "number of params not match the annotation. "
                    "{}, annotation: {}, params: {}".format(cls, annotation, params)
                )
            return tuple(
                cls.from_annotation(p, global_params, sub_annotation)
                for p, sub_annotation in zip(params, args)
            )

        # Union / Optional
        if origin is typing.Union:
            for option in args:
                try:
                    return cls.from_annotation(params, global_params, option)
                except Exception:
                    continue
            raise ValueError("no type of Union match the params {}".format(params))

        # 至此 annotation 应当是一个普通 class（非泛型）。

        # NoneType（来自 Optional[X] 内部分支）
        if annotation is type(None):
            if params is None:
                return None
            raise ValueError("expected None, got {}".format(params))

        if params is None:
            return None

        # Params 子类（或任何提供 from_json 的类）
        if isinstance(annotation, type) and hasattr(annotation, "from_json"):
            return annotation.from_json(params, global_params)

        # 已经是目标类型的实例
        if isinstance(annotation, type) and isinstance(params, annotation):
            return params

        # 基本类型 (str / int / float / bool / 自定义类...)
        if isinstance(params, dict):
            return annotation(**params)
        return annotation(params)


if __name__ == "__main__":
    pass
