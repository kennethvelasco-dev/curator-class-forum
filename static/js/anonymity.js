// Shows the anonymity notice only while "Post Anonymously" is checked.
// Without JavaScript the notice stays visible, which is the safe default.
(function () {
  "use strict";
  document.querySelectorAll("[data-anonymity-control]").forEach(function (control) {
    var toggle = control.querySelector("[data-anonymity-toggle]");
    var notice = control.querySelector("[data-anonymity-notice]");
    if (!toggle || !notice) { return; }
    function sync() { notice.hidden = !toggle.checked; }
    toggle.addEventListener("change", sync);
    sync();
  });
})();
