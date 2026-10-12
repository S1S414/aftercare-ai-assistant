// Model calls only follow the explicit suggestion button; writes never auto-retry.
(async () => {
  const $ = id => document.getElementById(id);
  let token, task, suggestion, busy = false;
  const labels = {draft:'待确认，尚未建单', completed:'已创建工单', cancelled:'已取消'};
  const modelNotice = document.createElement('p');
  modelNotice.id = 'model-notice';
  modelNotice.setAttribute('role', 'status');
  modelNotice.setAttribute('aria-live', 'polite');
  $('suggest').after(modelNotice);
  function modelStatus(message) {
    modelNotice.textContent = message;
    $('notice').textContent = message;
  }
  const dirty = () => task && ($('category').value !== task.category || $('edit-description').value !== task.description);
  function controls() {
    document.querySelectorAll('button').forEach(b => b.disabled = busy || !token);
    const ended = !task || task.state !== 'draft';
    ['category','edit-description','save','cancel'].forEach(id => $(id).disabled = busy || ended);
    $('confirm').disabled = busy || ended || dirty();
    $('suggest').disabled = busy || ended || dirty();
    $('apply-suggestion').disabled = busy || ended || !suggestion;
  }
  async function api(url, method='GET', data) {
    const r = await fetch(url, {method, headers:{'Content-Type':'application/json','X-CSRF-Token':token || ''}, ...(data ? {body:JSON.stringify(data)} : {})});
    const p = await r.json();
    if (!r.ok) throw Error(p.error?.message || '请求失败，请刷新并重新查看任务状态');
    return p.data;
  }
  function show(value) {
    modelNotice.textContent = '';
    suggestion = null; $('suggestion').hidden = true;
    task = value; $('draft').hidden = false;
    const option = [...$('order').options].find(o => Number(o.value) === task.order_id);
    $('summary').textContent = `${option?.textContent || '订单编号 '+task.order_id}；版本 ${task.version}；${labels[task.state]}`;
    $('category').value = task.category; $('edit-description').value = task.description;
    $('ticket').hidden = !task.ticket_id;
    if (task.ticket_id) $('ticket').href = '/tickets/' + task.ticket_id;
    controls();
  }
  async function act(fn) {
    if (busy) return;
    busy = true; controls(); $('notice').textContent = '正在处理……';
    try { show(await fn()); $('notice').textContent = '已保存：'+labels[task.state]; }
    catch(e) { $('notice').textContent = e.message + '。未自动重试；结果不确定时请刷新后打开已有任务查看。'; }
    finally { busy = false; controls(); }
  }
  $('new-task').onsubmit = e => {e.preventDefault(); act(() => api('/api/assistant/tasks','POST',{order_id:Number($('order').value),description:$('description').value}));};
  $('edit-task').onsubmit = e => {e.preventDefault(); act(() => api('/api/assistant/tasks/'+task.id,'PATCH',{version:task.version,category:$('category').value,description:$('edit-description').value}));};
  $('confirm').onclick = () => {if (!dirty()) act(() => api('/api/assistant/tasks/'+task.id+'/confirm','POST',{version:task.version}));};
  $('cancel').onclick = () => act(() => api('/api/assistant/tasks/'+task.id+'/cancel','POST',{version:task.version}));
  $('suggest').onclick = async () => {
    if (busy || dirty()) return;
    busy = true; suggestion = null; $('suggestion').hidden = true; controls();
    $('suggest').textContent = '正在整理，请稍候……';
    modelStatus('正在整理，最多一次模型调用，请勿重复点击……');
    try {
      const value = await api('/api/assistant/tasks/'+task.id+'/suggest','POST',{version:task.version});
      const usage = value.usage;
      const usageText = usage ? `输入 ${usage.prompt_tokens ?? '未知'} / 输出 ${usage.completion_tokens ?? '未知'} / 合计 ${usage.total_tokens ?? '未知'} Token` : '未知';
      modelStatus(`${value.answer} 请求编号：${value.local_request_id || '未调用'}；耗时 ${value.elapsed_ms ?? '未知'} ms；用量 ${usageText}`);
      if (value.status === 'suggested') {
        suggestion = value; $('suggestion').hidden = false;
        const names = {product:'商品问题',delivery:'配送问题',return_query:'退换咨询',other:'其他'};
        $('suggestion-text').textContent = `建议类型：${names[value.category]}。建议描述：${value.summary}`;
        $('suggestion-sources').replaceChildren();
        for (const s of value.citations) {const p=document.createElement('p'), a=document.createElement('a'); a.href=s.source_url; a.textContent=s.title+' · '+s.version; p.append(a); $('suggestion-sources').append(p);}
      }
    } catch(e) {modelStatus(e.message+' 未自动重试。');}
    finally {busy=false; $('suggest').textContent='请求模型整理（付费，单次调用）'; controls();}
  };
  $('apply-suggestion').onclick = () => {
    if (!suggestion || suggestion.version !== task.version) return;
    $('category').value=suggestion.category; $('edit-description').value=suggestion.summary;
    modelStatus('建议已填入，请核对并保存修改，尚未建单。'); controls();
  };
  ['category','edit-description'].forEach(id => $(id).addEventListener('input',controls));
  document.querySelectorAll('[data-task]').forEach(b => b.onclick = () => act(() => api('/api/assistant/tasks/'+b.dataset.task)));
  let cleanupToken = null;
  const refreshAfterDelete = count => {sessionStorage.setItem('aftercare-deleted',String(count)); window.location.reload();};
  const previousDelete = sessionStorage.getItem('aftercare-deleted');
  if (previousDelete !== null) {
    $('management-notice').textContent=`已从本地数据库删除 ${previousDelete} 条草稿及关联操作记录。数据库文件空间回收由本机维护者执行，未在此计算释放量。`;
    sessionStorage.removeItem('aftercare-deleted');
  }
  document.querySelectorAll('[data-select-group]').forEach(box => box.onchange = () => {
    document.querySelectorAll('[data-cleanup-item]').forEach(item => {if (item.dataset.group === box.dataset.selectGroup) item.checked=box.checked;});
  });
  $('cleanup-selected').onclick = () => {
    if (dirty()) { $('management-notice').textContent='请先保存正在编辑的草稿。'; return; }
    const selected=[...document.querySelectorAll('[data-cleanup-item]:checked')];
    if (!selected.length || selected.length>100) { $('management-notice').textContent='请选择1至100条草稿。'; return; }
    if (!window.confirm('将永久删除以下草稿及关联记录：\n'+selected.map(x=>x.parentElement.textContent.trim()).join('\n'))) return;
    manage(async()=>{const result=await api('/api/assistant/cleanup/selected','POST',{items:selected.map(x=>({id:x.dataset.cleanupItem,version:Number(x.dataset.version)})),confirmed:true}); refreshAfterDelete(result.deleted);});
  };
  async function manage(fn) {
    if (busy) return;
    busy = true; controls();
    $('management-notice').textContent = '正在处理……';
    try { await fn(); }
    catch(e) { $('management-notice').textContent = e.message + '。未自动重试，请刷新核对记录。'; }
    finally { busy = false; controls(); }
  }
  document.querySelectorAll('[data-delete-task]').forEach(b => b.onclick = () => {
    if (dirty()) { $('management-notice').textContent='当前草稿有未保存修改，请先保存，再删除记录。'; return; }
    if (!window.confirm(`删除 ${b.dataset.order} 的这份草稿？将删除草稿及操作记录，不可撤销，不影响订单。`)) return;
    manage(async () => {
      const result = await api('/api/assistant/tasks/'+b.dataset.deleteTask, 'DELETE', {version:Number(b.dataset.version),confirmed:true});
      refreshAfterDelete(result.deleted);
    });
  });
  $('cleanup-preview').onclick = () => manage(async () => {
    cleanupToken = null; $('cleanup-panel').hidden = true;
    const value = await api('/api/assistant/cleanup/preview', 'POST', {});
    $('cleanup-list').replaceChildren();
    for (const row of value.rows) {
      const li = document.createElement('li');
      li.textContent = `${row.order} · ${row.summary} · 取消于 ${row.cancelled_at}（北京时间）`;
      $('cleanup-list').append(li);
    }
    cleanupToken = value.token;
    $('cleanup-confirm').textContent = `确认删除这${value.rows.length}条`;
    $('cleanup-confirm').hidden = !value.rows.length;
    $('cleanup-panel').hidden = false;
    $('management-notice').textContent = value.rows.length ? '请核对预览；尚未删除任何记录。' : '没有符合7天条件的记录。';
  });
  $('cleanup-back').onclick = () => {cleanupToken=null; $('cleanup-panel').hidden=true; $('management-notice').textContent='已返回，未删除。';};
  $('cleanup-confirm').onclick = () => {
    if (dirty()) { $('management-notice').textContent='当前草稿有未保存修改，请先保存，再清理记录。'; return; }
    if (!cleanupToken || !window.confirm('确认永久删除预览中的草稿及其操作记录？不可撤销。')) return;
    manage(async () => {
      const result = await api('/api/assistant/cleanup/confirm', 'POST', {token:cleanupToken,confirmed:true});
      refreshAfterDelete(result.deleted);
    });
  };
  try {const session = await api('/api/session'); if (!session.user || session.user.role !== 'customer') throw Error('请以普通用户登录'); token = session.csrf_token; $('notice').textContent = '可以开始；保存草稿不会创建工单。'; controls();}
  catch(e) {$('notice').textContent = e.message;}
})();
