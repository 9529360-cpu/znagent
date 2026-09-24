'use strict';

const DEFAULT_MAX_MENU_ITEMS = 256;
const DEFAULT_MAX_MENU_DEPTH = 8;

function boundedText(value, max) {
  if (typeof value !== 'string' || value.length === 0) return null;
  return value.slice(0, max);
}

function boundedPositiveInteger(value, fallback, max) {
  return Number.isInteger(value) && value > 0 ? Math.min(value, max) : fallback;
}

function applicationMenuInventory(menu, options = {}) {
  const maxItems = boundedPositiveInteger(options.maxItems, DEFAULT_MAX_MENU_ITEMS, DEFAULT_MAX_MENU_ITEMS);
  const maxDepth = boundedPositiveInteger(options.maxDepth, DEFAULT_MAX_MENU_DEPTH, DEFAULT_MAX_MENU_DEPTH);
  const items = [];
  let truncated = false;

  function visit(rawItems, parentIndex, depth) {
    if (!Array.isArray(rawItems) || rawItems.length === 0) return;
    if (depth > maxDepth) {
      truncated = true;
      return;
    }
    for (const item of rawItems) {
      if (items.length >= maxItems) {
        truncated = true;
        return;
      }
      const submenuItems = Array.isArray(item?.submenu?.items) ? item.submenu.items : [];
      const index = items.length;
      items.push({
        index,
        parentIndex,
        depth,
        id: boundedText(item?.id, 240),
        label: boundedText(item?.label, 240),
        role: boundedText(item?.role, 120),
        type: boundedText(item?.type, 80),
        accelerator: boundedText(item?.accelerator, 120),
        enabled: item?.enabled !== false,
        visible: item?.visible !== false,
        checked: Boolean(item?.checked),
        hasSubmenu: submenuItems.length > 0
      });
      if (submenuItems.length > 0) visit(submenuItems, index, depth + 1);
    }
  }

  visit(Array.isArray(menu?.items) ? menu.items : [], null, 0);
  return {
    items,
    truncated,
    maxItems,
    maxDepth
  };
}

module.exports = {
  DEFAULT_MAX_MENU_ITEMS,
  DEFAULT_MAX_MENU_DEPTH,
  applicationMenuInventory
};
