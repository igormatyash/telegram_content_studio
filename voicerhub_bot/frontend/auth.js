const form = document.querySelector("#loginForm");
const error = document.querySelector("#error");
const googleEnabled = document.body.dataset.googleEnabled === "true";
const basePath = document.body.dataset.basePath || "";
document.querySelector("#oauthBlock").hidden = !googleEnabled;

form.addEventListener("submit", async event => {
  event.preventDefault();
  error.textContent = "";
  const button = form.querySelector("button[type=submit]");
  const old = button.textContent;
  button.disabled = true;
  button.innerHTML = `<span class="spinner"></span>${window.authT ? window.authT("Входимо…") : "Входимо…"}`;
  try {
    const response = await fetch(`${basePath}/api/login`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        username: document.querySelector("#username").value,
        password: document.querySelector("#password").value,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || (window.authT ? window.authT("Не вдалося увійти") : "Не вдалося увійти"));
    location.reload();
  } catch (reason) {
    error.textContent = window.authT ? window.authT(reason.message) : reason.message;
  } finally {
    button.disabled = false;
    button.textContent = old;
  }
});

document.querySelector("#resetHelp").addEventListener("click", event => {
  event.preventDefault();
  error.textContent = window.authT ? window.authT("Попросіть адміністратора workspace створити одноразове посилання для відновлення.") : "Попросіть адміністратора workspace створити одноразове посилання для відновлення.";
});
