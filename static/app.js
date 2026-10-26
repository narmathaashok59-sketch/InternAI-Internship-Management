document.addEventListener("DOMContentLoaded", () => {
  const search = document.getElementById("taskSearch");
  if (search) {
    search.addEventListener("input", () => {
      const query = search.value.toLowerCase().trim();
      document.querySelectorAll(".task-row").forEach(row => {
        row.style.display = row.innerText.toLowerCase().includes(query) ? "" : "none";
      });
    });
  }

  const today = new Date();
  const localDate = new Date(today.getTime() - today.getTimezoneOffset() * 60000)
    .toISOString().slice(0, 10);
  const reviewDate = document.getElementById("reviewDate");
  const deadline = document.getElementById("deadline");
  if (reviewDate) reviewDate.min = localDate;
  if (deadline) deadline.min = localDate;
  if (reviewDate && deadline) {
    deadline.addEventListener("change", () => {
      if (deadline.value) reviewDate.min = deadline.value > localDate ? deadline.value : localDate;
    });
  }
});
