window['initBloque_{slug}'] = function() {
    if (window[chartId]) window[chartId].destroy();  // destrucción previa obligatoria
    // ... construcción del gráfico con valores por defecto ...
};

document.addEventListener('DOMContentLoaded', function () {
    try { window['initBloque_{slug}']() } catch (e) { console.error(e) }
});
