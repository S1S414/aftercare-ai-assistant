const feedback = document.querySelector('#feedback');
const retry = document.querySelector('#retry-session');
const mutationButtons = [...document.querySelectorAll('#logout,#claim-ticket,#create-ticket button,#close-ticket button')];
let csrf = '';
let ready = false;

function notice(text, bad=false) { feedback.textContent=text; feedback.classList.toggle('error',bad); }
async function sessionReady() {
  ready=false; mutationButtons.forEach(b=>b.disabled=true);
  try {
    const response=await fetch('/api/session',{credentials:'same-origin'});
    if (!response.ok) throw new Error('读取会话失败');
    const {data}=await response.json();
    if (!data.user) { location.assign('/login'); return; }
    csrf=data.csrf_token; ready=true; retry.hidden=true;
    mutationButtons.forEach(b=>b.disabled=false); notice('');
  } catch(error) { notice(`${error.message}，请重试。`,true); retry.hidden=false; }
}
async function post(path,body) {
  const controller=new AbortController();
  const timeout=setTimeout(()=>controller.abort(),15000);
  try {
    const response=await fetch(path,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body),signal:controller.signal});
    const payload=await response.json();
    if (!response.ok) {
      if(response.status===401) location.assign('/login');
      if(payload.error?.code==='csrf_failed') { ready=false; retry.hidden=false; }
      throw new Error(payload.error?.message || '操作失败');
    }
    return payload.data;
  } catch(error) {
    if(error.name==='AbortError') throw new Error('请求超时，结果尚不确定。建单可保持原内容重试；领取或关闭请先刷新查看状态。');
    throw error;
  } finally { clearTimeout(timeout); }
}
async function execute(button,action) {
  if(!ready || button.disabled) return;
  button.disabled=true; notice('正在提交，请稍候……');
  try { await action(); }
  catch(error) { notice(error.message,true); }
  finally { button.disabled=!ready; }
}
retry.addEventListener('click',sessionReady);
document.querySelector('#logout').addEventListener('click',event=>execute(event.currentTarget,async()=>{ await post('/api/auth/logout',{}); location.assign('/login'); }));

const create=document.querySelector('#create-ticket');
if(create) {
  let attempt=null;
  create.addEventListener('submit',event=>{
    event.preventDefault();
    const description=document.querySelector('#description').value.trim();
    if(!description) { notice('请填写问题描述。',true); return; }
    const body={order_id:Number(create.dataset.orderId),category:document.querySelector('#category').value,description};
    const fingerprint=JSON.stringify(body);
    if(!attempt || attempt.fingerprint!==fingerprint) attempt={fingerprint,key:crypto.randomUUID()};
    execute(create.querySelector('button'),async()=>{
      const data=await post('/api/tickets',{...body,request_key:attempt.key});
      location.assign(`/tickets/${data.ticket.id}`);
    });
  });
}
const claim=document.querySelector('#claim-ticket');
if(claim) claim.addEventListener('click',()=>execute(claim,async()=>{ await post(`/api/staff/tickets/${claim.dataset.ticketId}/claim`,{}); location.reload(); }));
const close=document.querySelector('#close-ticket');
if(close) close.addEventListener('submit',event=>{
  event.preventDefault();
  const resolution=document.querySelector('#resolution').value.trim();
  if(!resolution) { notice('请填写处理结果。',true); return; }
  if(!confirm('确认保存处理结果并关闭？关闭后本版本不能重开。')) return;
  execute(close.querySelector('button'),async()=>{ await post(`/api/staff/tickets/${close.dataset.ticketId}/close`,{resolution}); location.reload(); });
});
document.querySelectorAll('time[datetime]').forEach(element=>{
  const date=new Date(element.dateTime);
  if(!Number.isNaN(date.getTime())) element.textContent=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'medium',timeStyle:'short',hour12:false}).format(date)+'（北京时间）';
});
sessionReady();
