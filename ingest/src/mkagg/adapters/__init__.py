"""Adapter registry.

Importing this package registers all four adapters. Recon collapsed the seven
MK stores onto these four platforms.
"""
from .base import Adapter, all_adapters, get_adapter, register  # noqa: F401
from . import (aspnet_mk, magento, magento_html, sportvision,  # noqa: F401,E402
               woocommerce, woocommerce_html)                  # noqa: F401,E402

__all__ = ["Adapter", "get_adapter", "all_adapters", "register",
           "sportvision", "magento", "magento_html", "woocommerce",
           "woocommerce_html", "aspnet_mk"]
