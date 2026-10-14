// NovaMart frontend: Cognito sign-in (USER_PASSWORD_AUTH over the public Cognito API, no SDK
// needed) + chat with the AgentCore Runtime through the Cognito-verified proxy.
// The session id lives in sessionStorage -> one conversation per browser tab (multi-turn memory).
const C = window.NOVAMART;
const $ = (id) => document.getElementById(id);
const store = sessionStorage;

async function cognito(target, body) {
  const r = await fetch(`https://cognito-idp.${C.region}.amazonaws.com/`, {
    method: 'POST',
    headers: {'Content-Type': 'application/x-amz-json-1.1', 'X-Amz-Target': `AWSCognitoIdentityProviderService.${target}`},
    body: JSON.stringify(body)});
  const data = await r.json();
  if (!r.ok) throw new Error(data.message || data.__type || 'Cognito error');
  return data;
}

function claims(jwt) { return JSON.parse(atob(jwt.split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))); }

function tabSession() {
  let s = store.getItem('nm_session');
  if (!s) { s = crypto.getRandomValues(new Uint32Array(2)).reduce((a, n) => a + n.toString(16), ''); store.setItem('nm_session', s); }
  return s;
}

function add(cls, text) {
  const d = document.createElement('div'); d.className = `msg ${cls}`; d.textContent = text;
  $('messages').appendChild(d); $('messages').scrollTop = 1e9; return d;
}

function showChat() {
  const id = claims(store.getItem('nm_id'));
  $('who').textContent = `${id.name || id['cognito:username']} · ${id['custom:customer_id']} (${id['custom:tier'] || ''})`;
  $('login-view').hidden = true; $('chat-view').hidden = false; $('logout').hidden = false;
  $('meta').textContent = `Conversation ${tabSession()} (this tab)`;
  if (!$('messages').childElementCount) add('sys', 'Hi! How can NovaMart help you today?');
  $('prompt').focus();
}

$('login-form').onsubmit = async (e) => {
  e.preventDefault(); $('login-error').textContent = '';
  try {
    const r = await cognito('InitiateAuth', {AuthFlow: 'USER_PASSWORD_AUTH', ClientId: C.clientId,
      AuthParameters: {USERNAME: $('username').value.trim(), PASSWORD: $('password').value}});
    if (!r.AuthenticationResult) throw new Error(`Unsupported challenge: ${r.ChallengeName}`);
    store.setItem('nm_access', r.AuthenticationResult.AccessToken);
    store.setItem('nm_id', r.AuthenticationResult.IdToken);
    $('password').value = ''; showChat();
  } catch (err) { $('login-error').textContent = err.message; }
};

$('chat-form').onsubmit = async (e) => {
  e.preventDefault();
  const prompt = $('prompt').value.trim(); if (!prompt) return;
  $('prompt').value = ''; $('send').disabled = true;
  add('user', prompt); const wait = add('sys', 'NovaMart agents are working on it...');
  try {
    const r = await fetch(C.proxyUrl, {method: 'POST',
      headers: {'Content-Type': 'application/json', Authorization: `Bearer ${store.getItem('nm_access')}`},
      body: JSON.stringify({prompt, session_id: tabSession()})});
    const data = await r.json();
    if (r.status === 401) { wait.textContent = 'Your sign-in expired - please sign in again.'; return logout(false); }
    wait.remove();
    if (!r.ok) add('sys', `Error: ${data.error || r.status}`);
    else { add('bot', data.reply); $('meta').textContent = `Conversation ${tabSession()} (this tab) · turn ${data.turn || ''} · runtime session ${data.session_id}`; }
  } catch (err) { wait.textContent = `Network error: ${err.message}`; }
  finally { $('send').disabled = false; $('prompt').focus(); }
};

function logout(clear = true) {
  ['nm_access', 'nm_id'].forEach((k) => store.removeItem(k));
  if (clear) { store.removeItem('nm_session'); $('messages').innerHTML = ''; }
  $('chat-view').hidden = true; $('login-view').hidden = false; $('logout').hidden = true; $('who').textContent = '';
}
$('logout').onclick = () => logout(true);
$('new-session').onclick = () => { store.removeItem('nm_session'); $('messages').innerHTML = ''; showChat(); };
if (store.getItem('nm_id') && claims(store.getItem('nm_id')).exp * 1000 > Date.now()) showChat();
