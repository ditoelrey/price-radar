"""Adapter registry.

Importing this package registers all four adapters. Recon collapsed the seven
MK stores onto these four platforms.
"""
from .base import Adapter, all_adapters, get_adapter, register  # noqa: F401
from . import aspnet_mk, magento, sportvision, woocommerce      # noqa: F401,E402

__all__ = ["Adapter", "get_adapter", "all_adapters", "register",
           "sportvision", "magento", "woocommerce", "aspnet_mk"]
