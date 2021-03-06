import functools
import inspect

from graphgallery.utils.type_check import is_list_like, is_scalar_like
from graphgallery.utils.shape import get_length
from graphgallery.utils.shape import repeat


def cal_outpus(func, args, kwargs, type_check=True):

    if is_list_like(args) and not is_scalar_like(args[0]):
        if type_check:
            assert_same_type(*args)
        return tuple(cal_outpus(func, arg, kwargs, type_check=type_check) for arg in args)

    return func(args, **kwargs)


class MultiInputs:
    
    wrapper_doc = """NOTE: This method is decorated by 
    'graphgallery.utils.decorators.MultiInputs',
    which takes multi inputs and yields multi outputs.
    """
    def __init__(self, *, type_check=True):
        self.type_check = type_check

    def __call__(self, func):
        doc = func.__doc__ if func.__doc__ else ""
        func.__doc__ = doc + self.wrapper_doc
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if len(args) == 1 and is_list_like(args[0]):
                args, = args

            outputs = cal_outpus(func, args, kwargs,
                                 type_check=self.type_check)
            if outputs is not None and is_list_like(outputs) and len(outputs) == 1:
                outputs, = outputs
            return outputs

        return wrapper


def assert_same_type(*inputs):
    first, *others = inputs
    # only one inputs
    if not others:
        return True

    _class = type(first)
    for ix, obj in enumerate(others):
        if not isinstance(obj, _class):
            raise TypeError(f"Input types don't agree. "
                            f"Type of the first input: {type(first)}, "
                            f"{ix+1}th input: {type(obj)}")

    return True


_BASE_VARS = ['hiddens', 'activations']


class EqualVarLength:
    """
    A decorator class which makes the values of the variables 
    equal in max-length. variables consist of 'hiddens', 'activations'
    and other customized ones in `include`.

    """

    def __init__(self, *, include: list=[], exclude: list=[], length_as: str='hiddens'):
        """

        Parameters
        ----------
        include : list, optional
            the customized variable names except for 
            'hiddens', 'activations', by default []
        exclude : list, optional
            the exclued variable names, by default []
        length_as : str, optional
            the variable name whose length is used for all variables,
            by default ['hiddens']
        """
        vars = list(include) + self.base_vars()
        vars = list(set(vars) - set(list(exclude)))
        assert length_as in vars
        self.vars = vars
        self.length_as = length_as

    def __call__(self, func):

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            ArgSpec = inspect.getfullargspec(func)

            if not ArgSpec.defaults or len(ArgSpec.args) != len(ArgSpec.defaults) + 1:
                raise Exception(
                    f"The '{func.__name__}' method must be defined with all default parameters.")

            model, *values = args
            for i in range(len(values), len(ArgSpec.args[1:])):
                values.append(ArgSpec.defaults[i])

            paras = dict(zip(ArgSpec.args[1:], values))
            paras.update(kwargs)

            repeated = get_length(paras.get(self.length_as, 0))
            for var in self.vars:
                # use `NOTHING` instead of `None` to avoid `None` exists
                val = paras.get(var, "NOTHING")
                if val != "NOTHING":
                    paras[var] = repeat(val, repeated)

            return func(model, **paras)
        return wrapper

    @staticmethod
    def base_vars():
        return _BASE_VARS

