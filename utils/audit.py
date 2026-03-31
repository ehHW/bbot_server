"""
审计日志工具模块
"""
from user.models import AuditLog


def build_request_metadata(request) -> dict:
    """从请求对象中提取元数据（IP地址、User-Agent）"""
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip_address = forwarded_for.split(",")[0].strip() if forwarded_for else request.META.get("REMOTE_ADDR", "")
    return {
        "ip_address": ip_address,
        "user_agent": request.META.get("HTTP_USER_AGENT", "")[:500],
    }


def write_audit_log(
    request,
    action: str,
    status_value: str,
    detail: str = "",
    target=None,
    metadata=None,
) -> None:
    """
    记录审计日志
    
    Args:
        request: Django请求对象
        action: 操作类型 (login, create, update, delete, kickout, protect_block)
        status_value: 操作状态 (success, failed, blocked)
        detail: 详细说明
        target: 操作的目标对象（可选）
        metadata: 额外元数据（可选）
    """
    request_meta = build_request_metadata(request)
    target_type = ""
    target_id = ""
    target_repr = ""
    
    if target is not None:
        target_type = target.__class__.__name__
        target_id = str(getattr(target, "pk", "") or "")
        target_repr = str(target)[:255]

    AuditLog.objects.create(
        actor=request.user if getattr(request, "user", None) and request.user.is_authenticated else None,
        action=action,
        status=status_value,
        detail=detail[:500],
        target_type=target_type,
        target_id=target_id,
        target_repr=target_repr,
        metadata=metadata or {},
        ip_address=request_meta["ip_address"],
        user_agent=request_meta["user_agent"],
    )
