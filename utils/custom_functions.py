# Compat shim — sera supprimé une fois GenericProfile migré
from core.tool_registry import registry

custom_tool = registry.render()  # retourne le même blob qu'avant
