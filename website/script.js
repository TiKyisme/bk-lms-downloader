const toggle = document.querySelector(".nav-toggle");
const links = document.querySelector(".nav-links");

if (toggle && links) {
  toggle.addEventListener("click", () => {
    const open = links.classList.toggle("is-open");
    toggle.setAttribute("aria-expanded", String(open));
  });
}

const video = document.querySelector("#demo-video");
const demoFrame = document.querySelector(".demo-frame");

if (video && demoFrame) {
  video.addEventListener("loadeddata", () => demoFrame.classList.add("has-video"), { once: true });
  video.addEventListener("error", () => demoFrame.classList.remove("has-video"), { once: true });
}
