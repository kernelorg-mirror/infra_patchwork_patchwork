$( document ).ready(function() {
    // Diff color scheme selector, persisted client-side in a cookie
    const diffColorSchemeSelect = document.getElementById("diff-color-scheme");
    if (diffColorSchemeSelect) {
        diffColorSchemeSelect.value = Cookies.get("diff_color_scheme") || "accessible";

        diffColorSchemeSelect.addEventListener("change", function() {
            Cookies.set("diff_color_scheme", diffColorSchemeSelect.value, {
                expires: 365,
                sameSite: "strict",
            });
        });
    }
});
