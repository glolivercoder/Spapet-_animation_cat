"""Módulo 4/5 — Onlook Bridge: edição visual do preview persistida no código."""
from __future__ import annotations

import html as html_module
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EDITABLE_EXTENSIONS = {".html", ".htm", ".tsx", ".jsx"}
VOID_TAGS = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}


class ElementMatch:
    def __init__(
        self,
        tag: str,
        attrs: str,
        body: str,
        close: str,
        start: int,
        end: int,
        open_end: int,
        close_start: int,
        is_self_closing: bool = False,
    ):
        self.tag = tag
        self.attrs = attrs
        self.body = body
        self.close = close
        self.start = start
        self.end = end
        self.open_end = open_end
        self.close_start = close_start
        self.is_self_closing = is_self_closing

    def group(self, name: str | int = 0) -> str | None:
        if name == "tag":
            return self.tag
        if name == "attrs":
            return self.attrs
        if name == "body":
            return self.body
        if name == "close":
            return self.close
        if name == 0:
            return self.tag + self.attrs + self.body + self.close
        return None


def _selector_token(selector: str) -> str:
    if selector.startswith("[data-tag="):
        value = selector.split("=", 1)[1].strip().strip('"').strip("'").rstrip("]")
        return rf'\bdata-tag\s*=\s*["\']{re.escape(value)}["\']'
    clean = selector.lstrip("#.")
    if selector.startswith("#"):
        return rf'\bid\s*=\s*["\']{re.escape(clean)}["\']'
    if selector.startswith("."):
        return rf'\bclass(?:Name)?\s*=\s*["\'][^"\']*\b{re.escape(clean)}\b[^"\']*["\']'
    return rf'(?:\bid|\bdata-tag)\s*=\s*["\']{re.escape(clean)}["\']'


def _find_element(html: str, selector: str) -> ElementMatch | None:
    s = selector.strip()
    nth = None
    nth_match = re.search(r':nth\((\d+)\)$', s)
    if nth_match:
        nth = int(nth_match.group(1))
        s = s[:nth_match.start()]

    expected_tag = None
    token_pattern = None

    if s.startswith("#"):
        token_pattern = rf'\bid\s*=\s*["\']{re.escape(s[1:])}["\']'
    elif s.startswith("."):
        token_pattern = rf'\bclass(?:Name)?\s*=\s*["\'][^"\']*\b{re.escape(s[1:])}\b[^"\']*["\']'
    elif s.startswith("[") and "=" in s:
        attr_name, attr_val = s.strip("[]").split("=", 1)
        attr_name = attr_name.strip()
        attr_val = attr_val.strip("\"'")
        token_pattern = rf'\b{re.escape(attr_name)}\s*=\s*["\']{re.escape(attr_val)}["\']'
    elif "." in s:
        parts = s.split(".", 1)
        expected_tag = parts[0]
        token_pattern = rf'\bclass(?:Name)?\s*=\s*["\'][^"\']*\b{re.escape(parts[1])}\b[^"\']*["\']'
    elif "#" in s:
        parts = s.split("#", 1)
        expected_tag = parts[0]
        token_pattern = rf'\bid\s*=\s*["\']{re.escape(parts[1])}["\']'
    else:
        expected_tag = s
        token_pattern = None

    tag_regex = re.escape(expected_tag) if expected_tag else r'\w+'
    open_re = re.compile(rf'<(?P<tag>{tag_regex})(?P<attrs>[^>]*)>', re.IGNORECASE)

    current_idx = 0
    for m in open_re.finditer(html):
        tag = m.group("tag")
        attrs = m.group("attrs")
        if token_pattern and not re.search(token_pattern, attrs, re.IGNORECASE):
            continue

        if nth is not None and current_idx != nth:
            current_idx += 1
            continue

        start = m.start()
        open_end = m.end()

        # Check if void or self-closing
        is_void = tag.lower() in VOID_TAGS
        is_self_closing = is_void or attrs.strip().endswith("/")

        if is_self_closing:
            return ElementMatch(tag, attrs, "", "", start, open_end, open_end, open_end, is_self_closing=True)

        # Scan for matching closing tag tracking nested depth
        depth = 1
        pos = open_end
        tag_scan = re.compile(rf'<(?P<is_close>/)?{re.escape(tag)}(?P<attrs>[^>]*)>', re.IGNORECASE)

        close_found = False
        close_start = open_end
        close_end = open_end
        for sm in tag_scan.finditer(html, pos):
            if sm.group("is_close"):
                depth -= 1
                if depth == 0:
                    close_start = sm.start()
                    close_end = sm.end()
                    close_found = True
                    break
            else:
                sm_attrs = sm.group("attrs")
                if not sm_attrs.strip().endswith("/"):
                    depth += 1

        if close_found:
            body = html[open_end:close_start]
            close = html[close_start:close_end]
            return ElementMatch(tag, attrs, body, close, start, close_end, open_end, close_start, is_self_closing=False)
        else:
            return ElementMatch(tag, attrs, "", "", start, open_end, open_end, open_end, is_self_closing=True)

    return None


def _merge_style(existing: str, new_prop: str) -> str:
    key = new_prop.split(":", 1)[0].strip().lower()
    parts = [part.strip() for part in existing.split(";") if part.strip()]
    parts = [part for part in parts if part.split(":", 1)[0].strip().lower() != key]
    parts.append(new_prop.strip())
    return "; ".join(parts)


def _merge_class(existing: str, value: str) -> str:
    classes = existing.split()
    if value.startswith("+"):
        classes.append(value[1:].strip())
    elif value.startswith("-"):
        classes = [name for name in classes if name != value[1:].strip()]
    else:
        classes = value.split()
    unique: list[str] = []
    for name in classes:
        if name and name not in unique:
            unique.append(name)
    return " ".join(unique)


def _set_attr(attrs: str, name: str, value: str) -> str:
    pattern = re.compile(rf'({name}\s*=\s*[\'"])([^\'"]*)([\'"])', re.IGNORECASE)
    if pattern.search(attrs):
        return pattern.sub(lambda match: match.group(1) + value + match.group(3), attrs, count=1)
    
    trailing_slash = attrs.strip().endswith("/")
    clean_attrs = attrs.rstrip().rstrip("/").rstrip() if trailing_slash else attrs
    new_attrs = f'{clean_attrs} {name}="{value}"'
    if trailing_slash:
        new_attrs += " /"
    return new_attrs


def apply_visual_edit(html: str, selector: str, kind: str, value: str) -> str:
    return apply_visual_edits(html, selector, [(kind, value)])


def apply_visual_edits(html: str, selector: str, edits: list[tuple[str, str]]) -> str:
    match = _find_element(html, selector)
    if not match:
        raise ValueError(f"selector não encontrado: {selector}")
    tag = match.tag
    attrs = match.attrs
    body = match.body

    for kind, value in edits:
        if kind == "text":
            body = html_module.escape(value)
        elif kind in {"style", "color"}:
            style_match = re.search(r'style\s*=\s*[\'"]([^\'"]*)[\'"]', attrs, re.IGNORECASE)
            merged = _merge_style(style_match.group(1), value) if style_match else value
            attrs = _set_attr(attrs, "style", merged)
        elif kind == "class":
            class_match = re.search(r'class\s*=\s*[\'"]([^\'"]*)[\'"]', attrs, re.IGNORECASE)
            merged = _merge_class(class_match.group(1), value) if class_match else value
            attrs = _set_attr(attrs, "class", merged)
        elif kind == "className":
            class_match = re.search(r'className\s*=\s*[\'"]([^\'"]*)[\'"]', attrs, re.IGNORECASE)
            merged = _merge_class(class_match.group(1), value) if class_match else value
            attrs = _set_attr(attrs, "className", merged)
        else:
            raise ValueError(f"kind inválido: {kind}")

    if match.is_self_closing or not match.close:
        trailing_slash = " /" if attrs.strip().endswith("/") or match.is_self_closing else ""
        clean_attrs = attrs.rstrip().rstrip("/").rstrip()
        replacement = f"<{tag}{clean_attrs}{trailing_slash}>"
    else:
        replacement = f"<{tag}{attrs}>{body}</{tag}>"

    return html[: match.start] + replacement + html[match.end :]


def build_onlook_script() -> str:
    return """
<script>
(() => {
  if (window.__onlookBridgeLoaded) return;
  window.__onlookBridgeLoaded = true;
  const urlParams = new URLSearchParams(location.search);
  const FILE = urlParams.get('file') || 'static/preview.html';
  let mode = urlParams.get('mode') || (window.parent !== window ? 'design' : 'interact');
  let selectedEl = null;

  const hex = (value) => {
    if (!value) return '#000000';
    if (value.startsWith('#')) return value;
    const parts = String(value).match(/\\d+/g);
    if (!parts) return '#000000';
    return '#' + parts.slice(0, 3).map(n => Number(n).toString(16).padStart(2, '0')).join('');
  };

  const getSelector = (el) => {
    if (!el || el === document.body) return 'body';
    if (el.id) return '#' + el.id;
    if (el.dataset && el.dataset.oid) return '[data-oid="' + el.dataset.oid + '"]';
    if (el.dataset && el.dataset.tag) return '[data-tag="' + el.dataset.tag + '"]';
    
    const tag = el.tagName.toLowerCase();
    let sel = tag;
    if (el.className && typeof el.className === 'string') {
      const cleanClass = el.className.replace('onlook-active-selection', '').trim().split(/\\s+/)[0];
      if (cleanClass) sel = tag + '.' + cleanClass;
    }

    try {
      const matches = Array.from(document.querySelectorAll(sel));
      if (matches.length > 1) {
        const idx = matches.indexOf(el);
        if (idx >= 0) return `${sel}:nth(${idx})`;
      }
    } catch (e) {}

    return sel;
  };

  const buildTree = (el) => {
    if (!el || el.nodeType !== 1) return null;
    if (['script', 'style', 'noscript'].includes(el.tagName.toLowerCase())) return null;
    const children = [];
    for (const child of el.children) {
      const node = buildTree(child);
      if (node) children.push(node);
    }
    return {
      tag: el.tagName.toLowerCase(),
      id: el.id || '',
      classes: typeof el.className === 'string' ? el.className.replace('onlook-active-selection', '').trim() : '',
      selector: getSelector(el),
      text: (el.children.length === 0 ? el.textContent.trim().slice(0, 40) : ''),
      children: children
    };
  };

  const notifyTree = () => {
    const tree = buildTree(document.body);
    if (window.parent !== window) {
      window.parent.postMessage({ type: 'onlook:tree', tree: tree }, '*');
    }
  };

  const applySelectionStyle = (el) => {
    document.querySelectorAll('.onlook-active-selection').forEach(n => {
      n.classList.remove('onlook-active-selection');
      n.style.outline = '';
      n.style.outlineOffset = '';
    });
    if (el) {
      el.classList.add('onlook-active-selection');
      el.style.outline = '2px solid #ef4444';
      el.style.outlineOffset = '2px';
      selectedEl = el;
    } else {
      selectedEl = null;
    }
  };

  const updatePill = () => {
    const pill = document.getElementById('onlook-mode-toggle');
    if (!pill) return;
    pill.innerHTML = mode === 'design' 
      ? '<span style="color:#ef4444;font-size:13px;">✏️</span> Modo: <strong style="color:#f87171;">Editar Onlook</strong> <span style="font-size:10px;opacity:0.8;background:#334155;padding:2px 7px;border-radius:10px;">Clique p/ Navegar</span>' 
      : '<span style="color:#10b981;font-size:13px;">🖱️</span> Modo: <strong style="color:#34d399;">Navegar (Interativo)</strong> <span style="font-size:10px;opacity:0.8;background:#334155;padding:2px 7px;border-radius:10px;">Clique p/ Editar</span>';
  };

  // Hover indicator in design mode
  document.addEventListener('mouseover', (event) => {
    if (mode !== 'design') return;
    const el = event.target.closest('[id], [data-tag], main, div, button, h1, h2, h3, p, span, a, img');
    if (!el || el === selectedEl || el === document.body) return;
    el.style.outline = '1px dashed #34d399';
    el.style.outlineOffset = '1px';
  });

  document.addEventListener('mouseout', (event) => {
    if (mode !== 'design') return;
    const el = event.target;
    if (el && el !== selectedEl) {
      el.style.outline = '';
      el.style.outlineOffset = '';
    }
  });

  document.addEventListener('click', (event) => {
    if (event.target.closest('.view-switcher-bar') || event.target.closest('#onlook-mode-toggle')) return;
    if (mode !== 'design') return;
    const el = event.target.closest('[id], [data-tag], main, div, button, h1, h2, h3, p, span, a, img') || event.target;
    if (!el || el === document.body) return;
    event.preventDefault();
    event.stopPropagation();
    applySelectionStyle(el);

    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    const payload = {
      type: 'onlook:select',
      file: FILE,
      selector: getSelector(el),
      tag: el.tagName.toLowerCase(),
      text: (el.textContent || '').trim().slice(0, 500),
      color: hex(style.color),
      background: hex(style.backgroundColor),
      fontSize: style.fontSize,
      fontWeight: style.fontWeight,
      padding: style.padding,
      paddingTop: style.paddingTop,
      paddingRight: style.paddingRight,
      paddingBottom: style.paddingBottom,
      paddingLeft: style.paddingLeft,
      margin: style.margin,
      marginTop: style.marginTop,
      marginRight: style.marginRight,
      marginBottom: style.marginBottom,
      marginLeft: style.marginLeft,
      width: Math.round(rect.width) + 'px',
      height: Math.round(rect.height) + 'px',
      display: style.display,
      flexDirection: style.flexDirection,
      alignItems: style.alignItems,
      justifyContent: style.justifyContent,
      gap: style.gap,
      borderRadius: style.borderRadius,
      classes: typeof el.className === 'string' ? el.className.replace('onlook-active-selection', '').trim() : ''
    };
    if (window.parent !== window) window.parent.postMessage(payload, '*');
    else console.log('onlook:select', payload);
  }, true);

  window.addEventListener('message', (event) => {
    const data = event.data;
    if (!data) return;
    if (data.type === 'onlook:reload') location.reload();
    if (data.type === 'onlook:set-mode') {
      mode = data.mode;
      if (mode !== 'design') applySelectionStyle(null);
      updatePill();
    }
    if (data.type === 'onlook:select-by-selector') {
      try {
        let target = null;
        const nthMatch = data.selector.match(/^(.+):nth\\((\\d+)\\)$/);
        if (nthMatch) {
          const all = document.querySelectorAll(nthMatch[1]);
          target = all[parseInt(nthMatch[2])];
        } else {
          target = document.querySelector(data.selector);
        }
        if (target) {
          applySelectionStyle(target);
          target.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
          target.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
        }
      } catch (err) {}
    }
    if (data.type === 'onlook:request-tree') {
      notifyTree();
    }
  });

  // Notify parent on DOM load
  window.addEventListener('DOMContentLoaded', () => {
    notifyTree();
    // Floating Mode Toggle Pill
    if (!document.getElementById('onlook-mode-toggle')) {
      const pill = document.createElement('div');
      pill.id = 'onlook-mode-toggle';
      pill.style.cssText = 'position:fixed;bottom:16px;left:16px;z-index:999999;background:rgba(15,23,42,0.92);color:#fff;border:1px solid #38bdf8;padding:7px 14px;border-radius:24px;font-family:system-ui,-apple-system,sans-serif;font-size:12px;font-weight:600;display:flex;align-items:center;gap:8px;box-shadow:0 8px 24px rgba(0,0,0,0.3);cursor:pointer;backdrop-filter:blur(8px);user-select:none;transition:all 0.2s ease;';
      pill.onclick = (e) => {
        e.stopPropagation();
        mode = mode === 'design' ? 'interact' : 'design';
        if (mode !== 'design') applySelectionStyle(null);
        updatePill();
        if (window.parent !== window) {
          window.parent.postMessage({ type: 'onlook:mode-changed', mode: mode }, '*');
        }
      };
      updatePill();
      document.body.appendChild(pill);
    }
  });
  setTimeout(notifyTree, 300);
})();
</script>
"""


def inject_bridge(html: str) -> str:
    script = build_onlook_script()
    return html.replace("</body>", script + "</body>") if "</body>" in html else html + script


def _safe_path(file_path: Path, root: Path | None = None) -> Path:
    base = (root or ROOT).resolve()
    target = file_path.resolve()
    if base not in target.parents and target != base:
        raise PermissionError("arquivo fora do projeto")
    return target


def commit_visual_edit(
    file_path: str | Path,
    selector: str,
    kind: str,
    value: str,
    root: Path | None = None,
) -> Path:
    return commit_visual_edits_batch(file_path, selector, [(kind, value)], root)


def commit_visual_edits_batch(
    file_path: str | Path,
    selector: str,
    edits: list[tuple[str, str]],
    root: Path | None = None,
) -> Path:
    target = _safe_path(Path(file_path), root)
    if target.suffix.lower() not in EDITABLE_EXTENSIONS:
        raise ValueError("extensão não editável")
    if not target.exists():
        raise FileNotFoundError(target)
    content = target.read_text(encoding="utf-8")
    
    normalized_edits = []
    for kind, val in edits:
        if target.suffix.lower() in {".tsx", ".jsx"} and kind == "class":
            kind = "className"
        normalized_edits.append((kind, val))
        
    updated = apply_visual_edits(content, selector, normalized_edits)
    target.write_text(updated, encoding="utf-8")
    return target
