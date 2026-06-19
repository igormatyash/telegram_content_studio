const action = document.body.dataset.action;
const basePath = document.body.dataset.basePath || "";
const token = new URLSearchParams(location.search).get("token") || "";
const invite = action === "invite";
document.querySelector("#title").textContent = window.authT ? window.authT(invite ? "Прийняти запрошення" : "Створити новий пароль") : (invite ? "Прийняти запрошення" : "Створити новий пароль");
document.querySelector("#subtitle").textContent = invite
  ? (window.authT ? window.authT("Приєднайтесь до команди Content Studio.") : "Приєднайтесь до команди Content Studio.")
  : (window.authT ? window.authT("Посилання одноразове. Після зміни пароля активні сесії буде завершено.") : "Посилання одноразове. Після зміни пароля активні сесії буде завершено.");
document.querySelector("#inviteFields").hidden = !invite;
if (invite && document.body.dataset.googleEnabled === "true") {
  document.querySelector("#inviteGoogle").hidden = false;
  document.querySelector("#inviteGoogleLink").href = `${basePath}/api/auth/google/start?invite=${encodeURIComponent(token)}`;
}

document.querySelector("#actionForm").addEventListener("submit", async event => {
  event.preventDefault();
  const error = document.querySelector("#error");
  error.textContent = "";
  const payload = {
    token,
    password: document.querySelector("#password").value,
  };
  if (invite) {
    payload.username = document.querySelector("#username").value;
    payload.display_name = document.querySelector("#displayName").value;
  }
  try {
    const response = await fetch(`${basePath}/${invite ? "api/invitations/accept" : "api/password-reset/complete"}`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || (window.authT ? window.authT("Не вдалося виконати дію") : "Не вдалося виконати дію"));
    location.href = "./";
  } catch (reason) {
    error.textContent = window.authT ? window.authT(reason.message) : reason.message;
  }
});
