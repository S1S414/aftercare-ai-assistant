let token = '';
const form = document.querySelector('#login-form');
const loginButton = document.querySelector('#login');
const logoutButton = document.querySelector('#logout');
const refreshButton = document.querySelector('#refresh');
const message = document.querySelector('#message');

async function call(path, body) {
  const options = {credentials: 'same-origin', headers: {}};
  if (body !== undefined) {
    options.method = 'POST';
    options.headers = {'Content-Type': 'application/json', 'X-CSRF-Token': token};
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error?.message || '请求失败');
  return result.data;
}

async function refresh() {
  loginButton.disabled = true;
  try {
    const data = await call('/api/session');
    token = data.csrf_token;
    form.hidden = !!data.user;
    document.querySelector('#identity').hidden = !data.user;
    document.querySelector('#user-summary').textContent = data.user
      ? `${data.user.username} · ${data.user.role === 'staff' ? '客服' : '普通用户'}` : '';
    message.textContent = data.user ? '身份已确认，可以进入工作台。' : '请输入本地演示账号和初始化时设置的密码。';
    loginButton.disabled = false;
  } catch (error) { message.textContent = `${error.message}；可点击刷新会话重试。`; }
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  loginButton.disabled = true;
  try {
    const data = await call('/api/auth/login', {
      username: document.querySelector('#username').value,
      password: document.querySelector('#password').value
    });
    token = data.csrf_token;
    document.querySelector('#password').value = '';
    location.assign('/');
  } catch (error) {
    message.textContent = error.message;
  } finally { loginButton.disabled = false; }
});
logoutButton.addEventListener('click', async () => {
  logoutButton.disabled = true;
  try { await call('/api/auth/logout', {}); await refresh(); }
  catch (error) { message.textContent = error.message; }
  finally { logoutButton.disabled = false; }
});
refreshButton.addEventListener('click', refresh);
refresh();
