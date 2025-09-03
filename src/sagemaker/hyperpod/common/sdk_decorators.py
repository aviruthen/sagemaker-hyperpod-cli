"""
SDK decorators for consistent error handling across all commands.
"""

import sys
import click
import functools
import logging
from kubernetes.client.exceptions import ApiException
from pydantic import ValidationError

logger = logging.getLogger(__name__)


def _extract_name_from_sdk_context(func, *args, **kwargs) -> str:
    """
    Extract resource name from SDK method context.
    
    SDK methods typically get name from:
    1. self.metadata.name (for instance methods)
    2. 'name' parameter (for class methods like get())
    3. First positional argument after self
    
    Args:
        func: The SDK method being called
        *args: Positional arguments passed to the method
        **kwargs: Keyword arguments passed to the method
    
    Returns:
        str: Resource name or 'unknown' if not found
        
    Hint: Check if args[0] has metadata.name attribute, then check kwargs['name'], 
    then check if args[1] exists (name as second arg after self)
    """
    # 1. Instance method: check self.metadata.name
    if args and hasattr(args[0], 'metadata') and hasattr(args[0].metadata, 'name'):
        return args[0].metadata.name
    
    # 2. Systematic parameter name checking (like CLI decorators do)
    name_params = ['name', 'job_name', 'endpoint_name']
    for param_name in name_params:
        if param_name in kwargs and kwargs[param_name]:
            return kwargs[param_name]
    
    # 3. Check any parameter ending with '_name' (excluding namespace-related ones)
    for param_name, value in kwargs.items():
        if (param_name.endswith('_name') and 
            param_name not in ['namespace', 'pod_name'] and 
            value):
            return value
    
    # 4. Positional argument fallback
    if len(args) > 1 and isinstance(args[1], str):
        return args[1]
    
    return 'unknown'
    

def _extract_namespace_from_sdk_context(func, *args, **kwargs) -> str:
    """
    Extract namespace from SDK method context.
    
    SDK methods typically get namespace from:
    1. self.metadata.namespace (for instance methods)
    2. 'namespace' parameter (for class methods)
    3. get_default_namespace() as fallback
    
    Args:
        func: The SDK method being called
        *args: Positional arguments passed to the method
        **kwargs: Keyword arguments passed to the method
    
    Returns:
        str: Namespace name or 'default' if not found
        
    Hint: Similar to name extraction but check for namespace attribute/parameter,
    import get_default_namespace from utils as fallback
    """
    # 1. Instance method: check self.metadata.namespace
    if args and hasattr(args[0], 'metadata') and hasattr(args[0].metadata, 'namespace'):
        namespace = args[0].metadata.namespace
        if namespace: 
            return namespace
    
    # 2. Check kwargs for namespace parameter
    namespace = kwargs.get('namespace')
    if namespace:
        return namespace
    
    # 3. Fallback to get_default_namespace() (like SDK code does)
    from sagemaker.hyperpod.common.utils import get_default_namespace
    return get_default_namespace()


def _extract_operation_type_from_sdk_method(func) -> str:
    """
    Extract operation type from SDK method name.
    
    SDK method names typically indicate operation:
    - create() -> 'create'
    - delete() -> 'delete' 
    - get() -> 'get'
    - list() -> 'list'
    
    Args:
        func: The SDK method being called
    
    Returns:
        str: Operation type or 'unknown' if not determinable
        
    Hint: Use func.__name__ to get method name, then map common method names
    to operation types
    """
    method_name = func.__name__.lower()
    if 'create' in method_name:
        return 'create'
    elif 'delete' in method_name:
        return 'delete'
    elif 'get' in method_name:
        return 'get'
    elif 'list' in method_name:
        return 'list'
    return 'unknown'

def _is_sdk_instance_method(func, *args) -> bool:
    """
    Determine if this is an instance method (has self) vs class method.
    
    Instance methods: job.delete(), endpoint.refresh()
    Class methods: Job.get(), Job.list()
    
    Args:
        func: The SDK method being called
        *args: Positional arguments (first arg is self for instance methods)
    
    Returns:
        bool: True if instance method, False if class method
        
    Hint: Check if args[0] has attributes like 'metadata' or if it's a class instance
    """
    return args and hasattr(args[0], 'metadata')


def _pre_invoke_sdk_exception_handling(func, *args, **kwargs):
    pass


def _post_invoke_sdk_exception_handling(e, func, *args, **kwargs):
    name = _extract_name_from_sdk_context(func, *args, **kwargs)
    namespace = _extract_namespace_from_sdk_context(func, *args, **kwargs)
    # BASIC EXCEPTION HANDLING
    if isinstance(e, ApiException):
        if e.status == 401:
            raise Exception(f"Credentials unauthorized.") from e
        elif e.status == 403:
            raise Exception(
                f"Access denied to resource '{name}' in namespace '{namespace}'."
            ) from e
        elif e.status == 404:
            # Basic 404 for SDK usage - CLI commands get enhanced 404 via decorator
            raise Exception(
                f"Resource '{name}' not found in namespace '{namespace}'. "
                f"Please check the resource name and namespace."
            ) from e
        elif e.status == 409:
            raise Exception(
                f"Resource '{name}' already exists in namespace '{namespace}'."
            ) from e
        elif 500 <= e.status < 600:
            raise Exception("Kubernetes API internal server error.") from e
        else:
            raise Exception(f"Unhandled Kubernetes error: {e.status} {e.reason}") from e

    if isinstance(e, ValidationError):
        raise Exception("Response did not match expected schema.") from e

    raise e

