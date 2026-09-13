"""
Verificación de contraste de los temas de la aplicación (WCAG 2.1).

No es un test de pytest a propósito: es una herramienta de diseño que se
corre a mano al tocar la paleta, e imprime la tabla completa para poder
justificar cada color. `tests/test_theme.py` sí falla automáticamente si
alguno de estos pares se rompe.

Uso:
    python -m scripts.check_theme_contrast
"""
from app.ui.theme import THEMES, contrast_ratio, critical_pairs

# Umbrales WCAG 2.1:
#   4.5:1 texto normal (AA) · 3:1 texto grande y componentes de UI (AA)
#   7:1 texto normal (AAA) — el objetivo del tema de alto contraste
LEVEL_LABEL = {4.5: "AA texto", 3.0: "AA componente", 7.0: "AAA texto"}


def main() -> int:
    failures = 0
    for theme_key, theme in THEMES.items():
        print(f"\n=== Tema: {theme.name} ({theme_key}) ===")
        print(f"{'par':46} {'ratio':>7}  {'mínimo':>7}  estado")
        print("-" * 78)
        for label, fg, bg, minimum in critical_pairs(theme):
            ratio = contrast_ratio(fg, bg)
            ok = ratio >= minimum
            if not ok:
                failures += 1
            print(f"{label:46} {ratio:7.2f}  {minimum:7.1f}  {'OK' if ok else 'FALLA'}")

    print("\n" + ("Todos los pares pasan." if not failures else f"{failures} par(es) por debajo del mínimo."))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
