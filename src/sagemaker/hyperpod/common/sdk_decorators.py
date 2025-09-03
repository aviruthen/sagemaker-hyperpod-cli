"""
SDK decorators for consistent error handling across all commands.
"""

import logging
from kubernetes.client.exceptions import ApiException
from pydantic import ValidationError

logger = logging.getLogger(__name__)


# ============================================================================
# Context Extraction Functions
# ============================================================================

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
    """
    # Check instance method: self.metadata.name
    if args and hasattr(args[0], 'metadata') and hasattr(args[0].metadata, 'name'):
        return args[0].metadata.name
    
    # Check common parameter names
    name_params = ['name', 'job_name', 'endpoint_name']
    for param_name in name_params:
        if param_name in kwargs and kwargs[param_name]:
            return kwargs[param_name]
    
    # Check any parameter ending with '_name' (excluding namespace-related ones)
    excluded_params = {'namespace', 'pod_name'}
    for param_name, value in kwargs.items():
        if param_name.endswith('_name') and param_name not in excluded_params and value:
            return value
    
    # Check positional argument fallback
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
    """
    # Check instance method: self.metadata.namespace
    if args and hasattr(args[0], 'metadata') and hasattr(args[0].metadata, 'namespace'):
        namespace = args[0].metadata.namespace
        if namespace:
            return namespace
    
    # Check kwargs for namespace parameter
    namespace = kwargs.get('namespace')
    if namespace:
        return namespace
    
    # Fallback to get_default_namespace()
    # Import here to avoid circular imports
    from . import utils
    return utils.get_default_namespace()


def _extract_operation_type_from_sdk_method(func) -> str:
    """
    Extract operation type from SDK method name.
    
    Args:
        func: The SDK method being called
    
    Returns:
        str: Operation type ('create', 'delete', 'get', 'list', or 'unknown')
    """
    method_name = func.__name__.lower()
    
    operation_mapping = {
        'create': 'create',
        'delete': 'delete',
        'get': 'get',
        'list': 'list'
    }
    
    for operation, operation_type in operation_mapping.items():
        if operation in method_name:
            return operation_type
    
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
    """
    return args and hasattr(args[0], 'metadata')


# ============================================================================
# Exception Handling Functions
# ============================================================================

def _pre_invoke_sdk_exception_handling(func, *args, **kwargs):
    """
    Pre-invoke exception handling for SDK methods.
    
    Currently no pre-processing is needed for SDK methods.
    """
    pass


def _post_invoke_sdk_exception_handling(e, func, *args, **kwargs):
    """
    Post-invoke exception handling for SDK methods.
    
    Provides basic exception handling with resource context.
    CLI commands get enhanced 404 handling via decorator.
    
    Args:
        e: The exception to handle
        func: The SDK method that was called
        *args: Positional arguments passed to the method
        **kwargs: Keyword arguments passed to the method
    
    Raises:
        Exception: Formatted exception with appropriate context
    """
    name = _extract_name_from_sdk_context(func, *args, **kwargs)
    namespace = _extract_namespace_from_sdk_context(func, *args, **kwargs)
    
    if isinstance(e, ApiException):
        if e.status == 401:
            raise Exception("Credentials unauthorized.") from e
        elif e.status == 403:
            raise Exception(
                f"Access denied to resource '{name}' in namespace '{namespace}'."
            ) from e
        elif e.status == 404:
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