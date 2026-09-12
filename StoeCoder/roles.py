import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from typing import List, Dict, Callable, Optional, Tuple

DEFAULT_ROLES = [
    {'name': 'planner', 'enabled': True, 'contract': 'Plan tasks and strategies.', 'model_mode': 'auto'},
    {'name': 'coder', 'enabled': True, 'contract': 'Write code and implement solutions.', 'model_mode': 'auto'},
    {'name': 'reviewer', 'enabled': True, 'contract': 'Review code and suggest improvements.', 'model_mode': 'auto'},
    {'name': 'debugger', 'enabled': True, 'contract': 'Debug issues and resolve problems.', 'model_mode': 'auto'},
    {'name': 'test-analyst', 'enabled': True, 'contract': 'Analyze test results and suggest improvements.', 'model_mode': 'auto'}
]


class RoleRegistry:
    def __init__(self, path: Path, models: Callable[[], List[Dict]], on_change: Callable):
        self.path = path
        self.models = models
        self.on_change = on_change
        self._lock = RLock()
        self._initialized_marker = path.parent / '.runtime' / 'roles-initialized'

    def _normalize_role(self, role: Dict) -> Dict:
        """Normalize a role dict with defaults and validate."""
        if not isinstance(role, dict):
            raise ValueError('Role must be an object')
        name = role.get('name', '')
        if not isinstance(name, str):
            raise ValueError("Role name must be a string.")
        if not name:
            raise ValueError("Role name cannot be empty.")

        # Validate name format
        import re
        if not re.fullmatch(r'[a-z][a-z0-9-]{0,47}', name):
            raise ValueError(f"Invalid role name format: {name}")

        enabled = role.get('enabled', True)
        if not isinstance(enabled, bool):
            raise ValueError("Role enabled must be a boolean.")

        contract = role.get('contract', '')
        if not isinstance(contract, str):
            raise ValueError("Role contract must be a string.")
        if len(contract) < 1 or len(contract) > 4000:
            raise ValueError("Role contract must be between 1 and 4000 characters.")

        model_mode = role.get('model_mode', 'auto')
        if model_mode not in ('auto', 'manual'):
            raise ValueError("Role model_mode must be 'auto' or 'manual'.")

        model = role.get('model')
        if model_mode == 'auto':
            if model is not None:
                raise ValueError("Auto roles cannot have a model specified.")
        else:  # manual
            if not isinstance(model, str) or not model:
                raise ValueError("Manual roles must specify a non-empty model name.")
            if len(model) > 200:
                raise ValueError("Model name must be at most 200 characters.")

        # Check for unknown fields
        allowed_fields = {'name', 'enabled', 'contract', 'model_mode', 'model'}
        for key in role:
            if key not in allowed_fields:
                raise ValueError(f"Unknown field in role: {key}")

        return {
            'name': name,
            'enabled': enabled,
            'contract': contract,
            'model_mode': model_mode,
            'model': model
        }

    def _normalize_roles(self, roles: List[Dict]) -> List[Dict]:
        """Normalize a list of role dicts."""
        if len(roles) > 32:
            raise ValueError("Maximum 32 roles allowed.")

        seen_names = set()
        normalized = []
        for role in roles:
            norm_role = self._normalize_role(role)
            name_lower = norm_role['name'].lower()
            if name_lower in seen_names:
                raise ValueError(f"Duplicate role name: {norm_role['name']}")
            seen_names.add(name_lower)
            normalized.append(norm_role)

        return normalized

    def _write(self, roles):
        normalized = self._normalize_roles(roles)
        payload = json.dumps({'format':'stoe.roles.v1', 'roles':normalized}, indent=2, ensure_ascii=False) + '\n'
        if len(payload.encode('utf-8')) > 200000:
            raise ValueError('Registry exceeds 200000 bytes')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=self.path.parent, prefix='.roles-', suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
                stream.write(payload)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def initialize(self):
        with self._lock:
            if self.path.exists():
                result = self.load()
            elif self._initialized_marker.exists():
                raise RuntimeError('Initialized role registry is missing; restore it explicitly')
            else:
                self._write(DEFAULT_ROLES)
                result = self.load()
            self._initialized_marker.parent.mkdir(parents=True, exist_ok=True)
            self._initialized_marker.touch()
            return result

    def load(self):
        with self._lock:
            if not self.path.exists():
                raise RuntimeError('Initialized role registry is missing; restore it explicitly')
            with self.path.open('rb') as stream:
                payload = stream.read(200001)
            if len(payload) > 200000:
                raise ValueError('Registry exceeds 200000 bytes')
            try:
                data = json.loads(payload.decode('utf-8'))
            except (UnicodeError, ValueError) as exc:
                raise ValueError('Invalid role registry JSON') from exc
            if not isinstance(data, dict) or set(data) != {'format','roles'} or data['format'] != 'stoe.roles.v1' or not isinstance(data['roles'], list):
                raise ValueError('Invalid role registry schema')
            return {'format':'stoe.roles.v1', 'roles':self._normalize_roles(data['roles'])}

    def save(self, role, original_name=None):
        with self._lock:
            roles = self.load()['roles']
            normalized = self._normalize_role(role)
            before = next((r for r in roles if r['name'] == original_name), None)
            if original_name is not None and before is None:
                raise ValueError('Role to edit does not exist')
            if any(r['name'] == normalized['name'] and r['name'] != original_name for r in roles):
                raise ValueError('Duplicate role name')
            if before == normalized:
                return self.load()
            # Disabling preserves a saved unavailable manual model. Availability
            # is checked whenever manual settings are chosen, enabled, or used.
            if normalized['model_mode'] == 'manual' and (normalized['enabled'] or before is None or any(before[k] != normalized[k] for k in ('model_mode','model'))):
                if not any(m['name'] == normalized['model'] for m in self.models()):
                    raise RuntimeError(f'Manual model "{normalized["model"]}" is unavailable for role "{normalized["name"]}"')
            updated = [normalized if r['name'] == original_name else r for r in roles] if before else roles + [normalized]
            self._write(updated)
            self.on_change('updated' if before else 'created', before, normalized)
            return self.load()

    def delete(self, name):
        with self._lock:
            roles = self.load()['roles']
            before = next((r for r in roles if r['name'] == name), None)
            if before is None:
                raise ValueError('Role to delete does not exist')
            self._write([r for r in roles if r['name'] != name])
            self.on_change('deleted', before, None)
            return self.load()

    def resolve(self, required, choose):
        with self._lock:
            roles = {r['name']:r for r in self.load()['roles']}
        for name in required:
            if name not in roles or not roles[name]['enabled']:
                raise RuntimeError(f'Required role "{name}" is not configured or enabled.')
        selected = []
        for name in required:
            role = roles[name]
            if role['model_mode'] == 'auto':
                model, digest = choose(name)
            else:
                installed = next((m for m in self.models() if m['name'] == role['model']), None)
                if installed is None:
                    raise RuntimeError(f'Manual model "{role["model"]}" is unavailable for role "{name}".')
                model, digest = installed['name'], installed['digest']
            selected.append({**role, 'resolved_model':model, 'digest':digest})
        return {'selected':selected, 'disabled':[r['name'] for r in roles.values() if not r['enabled']]}
