// 单独准备CSRF，付费调用仅由点击触发；刷新页面不会重复调用。
(async () => {
  const form=document.querySelector('#model-ask'), button=form.querySelector('button'), output=document.querySelector('#model-result');
  let token='';
  try { const r=await fetch('/api/session'); const p=await r.json(); if(!r.ok || !p.data.user) throw Error(); token=p.data.csrf_token; button.disabled=false; }
  catch { output.hidden=false; output.textContent='无法准备模型问答，请刷新后重试。'; }
  form.addEventListener('submit',async event=>{
    event.preventDefault(); if(button.disabled) return;
    button.disabled=true; output.hidden=false; output.textContent='正在请求模型……';
    const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),30000);
    try {
      const response=await fetch('/api/knowledge/model-answer',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':token},body:JSON.stringify({q:document.querySelector('#model-question').value.trim()}),signal:controller.signal});
      const payload=await response.json(); if(!response.ok) throw Error(payload.error?.message || '请求失败');
      const data=payload.data; output.replaceChildren();
      const heading=document.createElement('h2'); heading.textContent=data.mode==='simulation' ? '规则模拟答复（未调用AI）' : ({answered:'模型回答（请核对引用）',abstained:'资料不足，暂不回答',unavailable:'模型未返回可用答案'})[data.status]; output.append(heading);
      const text=document.createElement('p'); text.textContent=data.answer; output.append(text);
      for(const source of (data.citations.length ? data.citations : data.related)) {
        const line=document.createElement('p'), link=document.createElement('a'); link.href=source.source_url; link.textContent=`${data.citations.length ? '引用' : '相关资料（非答案）'}：${source.title} · ${source.version}`; line.append(link); output.append(line);
      }
      const meta=document.createElement('small'); meta.textContent=`本地请求编号：${data.local_request_id || '未发出外部请求'}；耗时 ${data.elapsed_ms} ms；Token用量：${data.usage ? JSON.stringify(data.usage) : '未取得'}。`; output.append(meta);
    } catch(error) { output.textContent=error.name==='AbortError' ? '等待超时，服务端可能仍在处理；本次可能已计费，不自动重试。' : error.message; }
    finally { clearTimeout(timer); button.disabled=false; }
  });
})();
