// Executed inside the page via page.evaluate(). Produces the raw material
// for app.browser.observation.Observation. Kept as a small, auditable
// snippet rather than scattered inline JS strings.
(function ([maxElements, maxTextChars]) {
  function isVisible(el) {
    if (!(el instanceof Element)) return false;
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return (
      rect.width > 0 &&
      rect.height > 0 &&
      style.visibility !== "hidden" &&
      style.display !== "none"
    );
  }

  function labelFor(el) {
    if (el.id) {
      const lbl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (lbl) return lbl.textContent.trim();
    }
    const parentLabel = el.closest("label");
    if (parentLabel) return parentLabel.textContent.trim();
    return null;
  }

  function accessibleName(el) {
    const ariaLabel = el.getAttribute("aria-label");
    if (ariaLabel) return ariaLabel.trim();
    const labelledBy = el.getAttribute("aria-labelledby");
    if (labelledBy) {
      const ref = document.getElementById(labelledBy);
      if (ref) return ref.textContent.trim();
    }
    const label = labelFor(el);
    if (label) return label;
    if (el.tagName === "INPUT" && el.placeholder) return el.placeholder.trim();
    const text = (el.textContent || "").trim();
    if (text) return text.slice(0, 120);
    const value = el.getAttribute("value");
    if (value) return value.trim();
    return null;
  }

  function roleOf(el) {
    const explicit = el.getAttribute("role");
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    if (tag === "button") return "button";
    if (tag === "a" && el.hasAttribute("href")) return "link";
    if (tag === "input") {
      const type = (el.getAttribute("type") || "text").toLowerCase();
      if (type === "submit" || type === "button") return "button";
      if (type === "checkbox") return "checkbox";
      return "textbox";
    }
    if (tag === "select") return "combobox";
    if (tag === "textarea") return "textbox";
    return null;
  }

  const INTERACTIVE_SELECTOR =
    "button, a[href], input, select, textarea, [role], [onclick], [data-testid]";

  const elements = Array.from(document.querySelectorAll(INTERACTIVE_SELECTOR));
  const interactive = [];
  let idx = 0;
  for (const el of elements) {
    if (interactive.length >= maxElements) break;
    const visible = isVisible(el);
    interactive.push({
      element_id: `e${idx}`,
      tag: el.tagName.toLowerCase(),
      role: roleOf(el),
      accessible_name: accessibleName(el),
      label: labelFor(el),
      test_id: el.getAttribute("data-testid"),
      text: (el.textContent || "").trim().slice(0, 120) || null,
      input_type: el.tagName === "INPUT" ? el.getAttribute("type") || "text" : null,
      placeholder: el.getAttribute("placeholder"),
      is_visible: visible,
      is_disabled: el.disabled === true || el.getAttribute("aria-disabled") === "true",
    });
    idx += 1;
  }

  const formFields = [];
  document.querySelectorAll("input[name], select[name], textarea[name]").forEach((el) => {
    const fieldType = el.tagName === "INPUT" ? el.getAttribute("type") || "text" : el.tagName.toLowerCase();
    // Never capture password values into the observation at all - this is
    // the source the LLM prompt, evidence JSON, and screenshots are all
    // built from, so redacting here beats trying to catch it downstream.
    const rawValue = el.tagName === "SELECT" ? el.value : el.getAttribute("value");
    formFields.push({
      name: el.getAttribute("name"),
      field_type: fieldType,
      label: labelFor(el),
      value: fieldType === "password" ? null : rawValue,
      required: el.hasAttribute("required"),
    });
  });

  const banners = Array.from(
    document.querySelectorAll('[role="alert"], .flash, .banner, .alert, .error-banner')
  )
    .map((el) => el.textContent.trim())
    .filter((t) => t.length > 0)
    .slice(0, 10);

  const bodyText = (document.body.innerText || "").replace(/\s+/g, " ").trim();
  const truncated = bodyText.length > maxTextChars;

  return {
    url: window.location.href,
    title: document.title,
    visible_text: bodyText.slice(0, maxTextChars),
    interactive_elements: interactive,
    form_fields: formFields,
    banner_messages: banners,
    truncated: truncated,
  };
})
