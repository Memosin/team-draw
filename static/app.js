const copyButton = document.querySelector("[data-copy-link]");

if (copyButton) {
  copyButton.addEventListener("click", async () => {
    const link = document.querySelector("#share-url");
    const status = document.querySelector(".copy-status");
    try {
      await navigator.clipboard.writeText(link.value);
    } catch {
      link.select();
      document.execCommand("copy");
      link.setSelectionRange(0, 0);
    }
    status.textContent = "Copied";
    window.setTimeout(() => { status.textContent = ""; }, 1800);
  });
}