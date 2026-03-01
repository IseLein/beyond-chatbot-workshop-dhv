const form = document.getElementById("analyze-form");
const filesInput = document.getElementById("files");
const imagePreviewEl = document.getElementById("image-preview");
const summaryEl = document.getElementById("summary");
const statusEl = document.getElementById("status");
const parsedEl = document.getElementById("parsed");
const rawEl = document.getElementById("raw");
const submitBtn = document.getElementById("submit-btn");
let previewUrls = [];

function setLoading(isLoading) {
  submitBtn.disabled = isLoading;
  submitBtn.textContent = isLoading ? "Analyzing..." : "Analyze";
}

function clearImagePreviews() {
  for (const url of previewUrls) {
    URL.revokeObjectURL(url);
  }
  previewUrls = [];
  imagePreviewEl.innerHTML = "";
}

function renderSelectedImagePreviews() {
  clearImagePreviews();

  const imageFiles = Array.from(filesInput.files || []).filter((file) =>
    file.type.startsWith("image/")
  );

  if (imageFiles.length === 0) {
    imagePreviewEl.className = "image-preview-empty";
    imagePreviewEl.textContent = "No image selected.";
    return;
  }

  imagePreviewEl.className = "preview-grid";
  const cards = imageFiles.map((file) => {
    const url = URL.createObjectURL(file);
    previewUrls.push(url);
    return `
      <figure class="preview-card">
        <img src="${url}" alt="${file.name}" />
        <figcaption>${file.name}</figcaption>
      </figure>
    `;
  });
  imagePreviewEl.innerHTML = cards.join("");
}

filesInput.addEventListener("change", renderSelectedImagePreviews);

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const formData = new FormData(form);
  setLoading(true);
  renderSelectedImagePreviews();
  summaryEl.textContent = "Analyzing files...";
  statusEl.textContent = "Sending files to model...";

  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      body: formData,
    });

    const payload = await response.json();

    if (!response.ok) {
      throw new Error(payload.error || "Request failed");
    }

    statusEl.textContent = JSON.stringify(
      {
        model: payload.model,
        files: payload.files,
      },
      null,
      2
    );

    const summary = payload.parsed && typeof payload.parsed.summary === "string"
      ? payload.parsed.summary.trim()
      : "";
    summaryEl.textContent = summary || "No summary field found in parsed JSON.";

    parsedEl.textContent = payload.parsed
      ? JSON.stringify(payload.parsed, null, 2)
      : "Model did not return valid JSON.";

    rawEl.textContent = payload.raw || "";
  } catch (error) {
    summaryEl.textContent = "No summary available.";
    statusEl.textContent = `Error: ${error.message}`;
    parsedEl.textContent = "No parsed output.";
    rawEl.textContent = "";
  } finally {
    setLoading(false);
  }
});
