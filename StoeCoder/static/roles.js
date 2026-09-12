/* Role configuration is data. All runtime authority remains server-side. */
let roleRows = [], editingRole = null;
const roleElement = id => document.getElementById(id);

async function refreshRoles() {
  try {
    const data = await coderRequest('roles');
    roleRows = data.roles;
    const list = roleElement('worker-role-list');
    list.replaceChildren();
    for (const role of roleRows) {
      const row = document.createElement('div'); row.className = 'worker-role-row';
      const toggle = document.createElement('input'); toggle.type = 'checkbox'; toggle.checked = role.enabled;
      toggle.setAttribute('aria-label', 'Enable ' + role.name);
      toggle.onchange = async () => {
        toggle.disabled = true;
        try { await coderRequest('roles/save', {original_name:role.name, role:{...role,enabled:toggle.checked}}); }
        catch(e) { roleElement('worker-role-error').textContent = e.message; }
        await refreshRoles();
      };
      const name = document.createElement('span'); name.textContent = role.name; name.style.flex = '1';
      const model = document.createElement('span'); model.textContent = role.model_mode === 'auto' ? 'Auto' : role.model;
      if(!role.enabled) { name.style.opacity = '.5'; model.style.opacity = '.5'; }
      const edit = document.createElement('button'); edit.className='btn-ghost btn-sm'; edit.textContent='Edit'; edit.onclick=()=>editRole(role);
      const del = document.createElement('button'); del.className='btn-ghost btn-sm'; del.textContent='Delete'; del.onclick=()=>deleteRole(role.name);
      row.append(toggle,name,model,edit,del); list.append(row);
    }
  } catch(e) { roleElement('worker-role-error').textContent = e.message; }
}

async function editRole(role = null) {
  editingRole = role;
  roleElement('role-name').value=role?.name || '';
  roleElement('role-contract').value=role?.contract || '';
  roleElement('role-mode').value=role?.model_mode || 'auto';
  roleElement('role-enabled').checked=role?.enabled ?? true;
  roleElement('role-editor-error').textContent='';
  const select = roleElement('role-model'); select.replaceChildren();
  try {
    const models=await coderRequest('models');
    for(const model of models) { const option=document.createElement('option'); option.value=model.name; option.textContent=model.name; select.append(option); }
    if(role?.model && !models.some(m=>m.name===role.model)) {
      const option=document.createElement('option'); option.value=role.model; option.textContent=role.model+' (unavailable)'; select.append(option);
    }
    if(role?.model) select.value=role.model;
  } catch(e) { roleElement('role-editor-error').textContent='Models unavailable: '+e.message; }
  roleElement('role-editor').hidden=false; updateRoleMode();
}

function updateRoleMode() { roleElement('role-model').disabled=roleElement('role-mode').value!=='manual'; }
async function saveRole(event) {
  event.preventDefault();
  const mode=roleElement('role-mode').value;
  const role={name:roleElement('role-name').value, contract:roleElement('role-contract').value,
    enabled:roleElement('role-enabled').checked, model_mode:mode, model:mode==='manual'?roleElement('role-model').value:null};
  try {
    await coderRequest('roles/save',{role,original_name:editingRole?.name ?? null});
    roleElement('role-editor').hidden=true; roleElement('worker-role-error').textContent=''; await refreshRoles();
  } catch(e) { roleElement('role-editor-error').textContent=e.message; }
}
async function deleteRole(name) {
  if(!window.confirm('Delete role "'+name+'"? Its saved definition will be removed. Disable it instead to retain its settings.')) return;
  try { await coderRequest('roles/delete',{name}); roleElement('role-editor').hidden=true; await refreshRoles(); }
  catch(e) { roleElement('worker-role-error').textContent=e.message; }
}

function renderTaskProgress(state) {
  const p=state.progress || {percent:0,stage:'Idle'};
  roleElement('coder-stage-progress').value=p.percent;
  const report=state.task_report;
  roleElement('coder-stage-label').textContent=report ? `${report.outcome==='success'?'★':'✖'} ${report.outcome.toUpperCase()} · ${report.duration_seconds}s · ${p.percent}%` : `${p.percent}% · ${p.stage}`;
  const terminal=roleElement('coder-finished'); terminal.hidden=!report;
  if(report) {
    terminal.dataset.outcome=report.outcome;
    terminal.textContent=`${report.outcome==='success'?'★':'✖'} TASK FINISHED · ${report.outcome.toUpperCase()} · ${report.task_id}\n`+
      `duration=${report.duration_seconds}s | roles=${report.selected_roles.length} | model_calls=${report.model_calls} | tool_steps=${report.tool_steps} | checks=${report.checks_passed}/${report.checks_passed+report.checks_failed} PASS | reviewer=${report.review_verdict || 'not run'} | files=${report.files_changed.length} | +${report.diff_additions}/-${report.diff_deletions} | commit=${report.commit || 'no'} | push=${report.push || 'no'}`+
      (report.failure_condition?'\nfailure='+report.failure_condition:'');
  }
}
document.addEventListener('DOMContentLoaded', refreshRoles);
