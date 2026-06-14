const form = document.querySelector("#registerForm");
const error = document.querySelector("#error");
const basePath = document.body.dataset.basePath || "";
const referralCode = document.body.dataset.referralCode || "";
const referralRequested = new URLSearchParams(location.search).has("ref");
const googleEnabled = document.body.dataset.googleEnabled === "true";

document.querySelector("#oauthBlock").hidden = !googleEnabled;
document.querySelector("#referralWelcome").hidden = !referralCode;
if (referralRequested && !referralCode) {
  error.textContent = "Реферальне посилання недійсне або вже вимкнене. Ви можете зареєструватися напряму.";
}

document.querySelector("#workspaceName").addEventListener("input", event => {
  const slug = event.target.value
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  const target = document.querySelector("#workspaceSlug");
  if (!target.dataset.edited) target.value = slug;
});
document.querySelector("#workspaceSlug").addEventListener("input", event => {
  event.target.dataset.edited = "true";
});

form.addEventListener("submit", async event => {
  event.preventDefault();
  error.textContent = "";
  const button = form.querySelector("button[type=submit]");
  const old = button.textContent;
  button.disabled = true;
  button.innerHTML = '<span class="spinner"></span>Створюємо…';
  try {
    const response = await fetch(`${basePath}/api/register`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        username: document.querySelector("#username").value,
        password: document.querySelector("#password").value,
        email: document.querySelector("#email").value,
        display_name: document.querySelector("#displayName").value,
        workspace_name: document.querySelector("#workspaceName").value,
        workspace_slug: document.querySelector("#workspaceSlug").value,
        referral_code: document.querySelector("#referralCode").value,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Не вдалося зареєструватися");
    location.href = `${basePath}/dashboard`;
  } catch (reason) {
    error.textContent = reason.message;
  } finally {
    button.disabled = false;
    button.textContent = old;
  }
});
