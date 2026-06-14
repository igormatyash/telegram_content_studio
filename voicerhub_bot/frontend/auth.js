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
  button.innerHTML = '<span class="spinner"></span>Входимо…';
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
    if (!response.ok) throw new Error(data.detail || "Не вдалося увійти");
    location.reload();
  } catch (reason) {
    error.textContent = reason.message;
  } finally {
    button.disabled = false;
    button.textContent = old;
  }
});

document.querySelector("#resetHelp").addEventListener("click", event => {
  event.preventDefault();
  error.textContent = "Попросіть адміністратора workspace створити одноразове посилання для відновлення.";
});
