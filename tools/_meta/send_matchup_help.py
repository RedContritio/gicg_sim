"""Help-text renderer for ``tools._meta.send_matchup``.

Builds a usage block from the eval_service JSON Schema so adding a new
request field / new request kind requires only a schema edit, no CLI
code change. Split out of send_matchup.py to stay under the 300-line
pre-commit cap."""

from __future__ import annotations

from tools.remote.eval_service import DEFAULT_SOCKET_PATH
from tools._meta.send_matchup_schema import resolve_ref


def help_from_schema(schema: dict) -> str:
    lines = [
        'Usage: python -m tools.send_matchup [OPTIONS]',
        '',
        'Construct a request for tools.remote.eval_service and POST it to the socket.',
        'CLI flags mirror JSON fields (hyphens → underscores, dots for nesting).',
        '',
        'Global options:',
        '  --socket PATH     Unix-socket path (default: ' + DEFAULT_SOCKET_PATH + ')',
        '  --body PATH       load request body from JSON file (bypass CLI flags)',
        '  --stdin           load request body from stdin',
        '  --help            show this help and exit',
        '',
        'Schema (fetched from eval_service):',
    ]
    for branch in schema.get('oneOf', []):
        title = branch.get('title', '?')
        desc = branch.get('description', '')
        lines.append('')
        lines.append(f'  # kind: {title}')
        if desc:
            lines.append(f'  {desc}')
        required = set(branch.get('required', []))
        props = branch.get('properties', {})
        for name, field in props.items():
            flag = '--' + name.replace('_', '-')
            t = field.get('type', '')
            if isinstance(t, list):
                t = '|'.join(t)
            choices = field.get('enum')
            const = field.get('const')
            suffix_parts = [str(t)] if t else []
            if choices:
                suffix_parts.append(f'one of {choices}')
            if const is not None:
                suffix_parts.append(f'const {const!r}')
            if name in required:
                suffix_parts.append('required')
            if 'default' in field:
                suffix_parts.append(f'default={field["default"]!r}')
            suffix = ' | '.join(suffix_parts)
            fd = field.get('description', '')
            lines.append(f'    {flag:28s} {suffix}')
            if fd:
                lines.append(f'      {fd}')
    # Player variant help (discovered via $defs)
    player = schema.get('$defs', {}).get('player_spec')
    if player and 'oneOf' in player:
        lines.append('')
        lines.append('  # players[i] variants (discriminator: type)')
        for v in player['oneOf']:
            v_resolved = resolve_ref(schema, v['$ref']) if '$ref' in v else v
            type_prop = v_resolved.get('properties', {}).get('type', {})
            t = type_prop.get('const') or type_prop.get('enum')
            lines.append(f'    type = {t!r}')
            req_set = set(v_resolved.get('required', []))
            for name, field in v_resolved.get('properties', {}).items():
                if name == 'type':
                    continue
                flag = f'--players.i.{name.replace("_", "-")}'
                ty = field.get('type', '')
                parts = [str(ty)] if ty else []
                if name in req_set:
                    parts.append('required')
                if 'default' in field:
                    parts.append(f'default={field["default"]!r}')
                fd = field.get('description', '')
                lines.append(f'      {flag:30s} {" | ".join(parts)}')
                if fd:
                    lines.append(f'        {fd}')
    return '\n'.join(lines)
