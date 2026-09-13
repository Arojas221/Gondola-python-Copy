"""
Tests del sistema visual.

La accesibilidad de la paleta no se comprueba a ojo: cada par crítico
tiene un mínimo WCAG y este archivo falla si alguien lo baja. Si al tocar
un color el test se pone rojo, el color está mal — no el test.
"""
import pytest

from app.ui.theme import (
    DARK,
    FONT_SCALES,
    HIGH_CONTRAST,
    LIGHT,
    THEMES,
    build_stylesheet,
    contrast_ratio,
    critical_pairs,
    perceptual_distance,
    relative_luminance,
    scaled,
)


# ------------------------------------------------------------ contraste --
def test_contrast_ratio_extremes():
    """Negro sobre blanco es el máximo posible; un color contra sí mismo, el mínimo."""
    assert contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0, abs=0.01)
    assert contrast_ratio("#3D9BE5", "#3D9BE5") == pytest.approx(1.0, abs=0.001)


def test_contrast_ratio_is_symmetric():
    assert contrast_ratio("#141310", "#F2F0E6") == pytest.approx(
        contrast_ratio("#F2F0E6", "#141310")
    )


def test_relative_luminance_bounds():
    assert relative_luminance("#000000") == pytest.approx(0.0)
    assert relative_luminance("#FFFFFF") == pytest.approx(1.0)


@pytest.mark.parametrize("theme_key", list(THEMES))
def test_every_critical_pair_meets_its_minimum(theme_key):
    """
    Ningún par crítico de ningún tema puede quedar por debajo de su mínimo.

    Cubre texto (4.5:1, o 7:1 en alto contraste) y elementos no textuales
    como bordes y anillo de foco (3:1, WCAG 1.4.11).
    """
    palette = THEMES[theme_key]
    failures = [
        f"{label}: {contrast_ratio(fg, bg):.2f} < {minimum}"
        for label, fg, bg, minimum in critical_pairs(palette)
        if contrast_ratio(fg, bg) < minimum
    ]
    assert not failures, f"Tema '{theme_key}': " + "; ".join(failures)


def test_high_contrast_theme_reaches_aaa():
    """El tema de alto contraste existe para eso: su texto debe superar 7:1."""
    assert contrast_ratio(HIGH_CONTRAST.TEXT_PRIMARY, HIGH_CONTRAST.BG_APP) >= 7.0


def test_series_colors_are_not_the_brand_accent():
    """
    Los colores de dato no pueden ser el acento de marca.

    El acento ya significa "botón primario", "pestaña activa" y "etiqueta
    del sistema"; reutilizarlo como serie del dashboard hacía que un mismo
    amarillo tuviera cinco significados distintos en pantalla.
    """
    for palette in THEMES.values():
        assert palette.SERIES_TAKEN != palette.ACCENT
        assert palette.SERIES_RETURNED != palette.ACCENT


def test_series_colors_are_perceptually_separated():
    """
    Las dos series deben distinguirse entre sí.

    Se mide con ΔE en OKLab, no con la razón de contraste WCAG: en una
    paleta categórica las series tienen luminancia parecida a propósito
    (ninguna debe pesar más que la otra) y se separan por tono, así que
    WCAG las declararía indistinguibles justo cuando están bien elegidas.
    El piso de 8 es el mínimo; por debajo de eso hay que apoyarse en
    etiquetas directas o textura.
    """
    for key, palette in THEMES.items():
        distance = perceptual_distance(palette.SERIES_TAKEN, palette.SERIES_RETURNED)
        assert distance >= 15.0, f"Tema '{key}': las series solo se separan ΔE {distance:.1f}"


def test_perceptual_distance_of_identical_colors_is_zero():
    assert perceptual_distance("#D8C61A", "#D8C61A") == pytest.approx(0.0, abs=1e-6)


def test_perceptual_distance_separates_obvious_opposites():
    assert perceptual_distance("#000000", "#FFFFFF") > 50


# ------------------------------------------------------- hoja de estilos --
@pytest.mark.parametrize("theme_key", list(THEMES))
def test_stylesheet_builds_for_every_theme(theme_key):
    css = build_stylesheet(theme_key, 1.0)
    assert "QWidget" in css and len(css) > 1000


def test_stylesheet_defines_focus_indicator():
    """
    WCAG 2.4.7: sin indicador de foco visible, la navegación por teclado
    es imposible de seguir. Es el fallo que tenía la versión anterior.
    """
    for theme_key, palette in THEMES.items():
        css = build_stylesheet(theme_key, 1.0)
        assert ":focus" in css, f"Tema '{theme_key}' sin regla de foco"
        assert palette.FOCUS in css, f"Tema '{theme_key}' no usa su color de foco"


def test_stylesheet_neutralizes_inherited_panel_border():
    """
    Qt propaga el borde de un panel a sus etiquetas hijas: sin esta regla,
    cada QLabel dentro de una tarjeta aparecía con su propio recuadro.
    """
    css = build_stylesheet("dark", 1.0)
    assert "QFrame#panel QLabel" in css
    assert "border: none" in css


def test_font_families_have_fallbacks():
    """
    'Segoe UI' y 'Consolas' solo existen en Windows. Sin lista de reserva,
    el diseño cambiaba entre los equipos del propio equipo.
    """
    css = build_stylesheet("dark", 1.0)
    assert "sans-serif" in css and "monospace" in css


@pytest.mark.parametrize("scale_key", list(FONT_SCALES))
def test_font_scale_grows_controls_too(scale_key):
    """
    Al agrandar la letra tienen que crecer también los controles: si el
    texto crece dentro de un botón del mismo tamaño, el área en la que se
    puede hacer click se queda igual de pequeña y el texto toca el borde.
    """
    factor = FONT_SCALES[scale_key][0]
    css = build_stylesheet("dark", factor)
    assert f"font-size: {scaled(10, factor)}pt" in css
    assert "min-height" in css


def test_larger_scale_produces_larger_font():
    small = build_stylesheet("dark", FONT_SCALES["small"][0])
    xlarge = build_stylesheet("dark", FONT_SCALES["xlarge"][0])
    assert small != xlarge
    assert scaled(10, 0.9) < scaled(10, 1.5)


def test_scaled_rounds_to_half_points():
    assert scaled(10, 1.0) == 10
    assert scaled(9, 1.2) == 11.0
    assert scaled(10, 1.15) == 11.5


# ------------------------------------------------------------- catálogo --
def test_three_themes_are_registered():
    assert set(THEMES) == {"dark", "light", "high_contrast"}


def test_themes_declare_their_own_mode():
    assert DARK.is_dark and HIGH_CONTRAST.is_dark
    assert not LIGHT.is_dark


def test_every_palette_defines_every_color():
    """Ninguna paleta puede dejar un color sin definir o vacío."""
    reference = set(DARK.__dataclass_fields__)
    for key, palette in THEMES.items():
        assert set(palette.__dataclass_fields__) == reference
        for field in reference:
            if field in ("name", "is_dark"):
                continue
            value = getattr(palette, field)
            assert value, f"Tema '{key}': campo '{field}' vacío"
