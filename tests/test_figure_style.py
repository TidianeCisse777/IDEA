"""Style standard des figures, servi par le MCP (fiche graphs, STYLE_CODE) : exécuté tel qu'un agent le copie."""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from warehouse_context import GRAPHICS, STYLE_CODE  # noqa: E402

HAS_MPL = importlib.util.find_spec('matplotlib') is not None


class Sheet(unittest.TestCase):
    def test_the_code_is_served_by_the_sheet_not_by_a_local_file(self):
        self.assertIn(STYLE_CODE, GRAPHICS['purpose'])
        self.assertFalse((ROOT / 'scripts' / 'neolab_figures.py').exists())
        text = ' '.join(GRAPHICS.values())
        for rule in ('8 cm', '16 cm', '8 pt', 'italique', 'LÉGENDE DE FIGURE prête à coller',
                     'jamais un résultat ni une interprétation', 'OneDrive', 'gsw.z_from_p'):
            self.assertIn(rule, text)
        self.assertNotIn('nf.', text)


@unittest.skipUnless(HAS_MPL, 'matplotlib requis')
class CopiedAsIs(unittest.TestCase):
    def test_a_figure_has_its_print_size_italic_taxa_and_french_numbers(self):
        import matplotlib
        matplotlib.use('Agg')
        ns = {}
        exec(STYLE_CODE, ns)                      # what an agent pastes at the top of its script
        self.assertEqual(ns['taxon']('Oithona similis'), r'$\it{Oithona}$ $\it{similis}$')
        self.assertEqual(ns['taxon']('Pseudocalanus spp.'), r'$\it{Pseudocalanus}$ spp.')
        self.assertEqual(ns['taxon']('Harpacticoida'), 'Harpacticoida')
        self.assertEqual(ns['taxon']('Autres taxons (9)'), 'Autres taxons (9)')
        fig, ax = ns['figure']('page', hauteur_cm=9)
        ax.plot([0, 1500, 3000], [0, 50, 100])
        ax.set_title('Essai')
        ns['lettres']([ax])
        folder = tempfile.mkdtemp()
        paths = ns['enregistrer'](fig, 'essai', dossier=folder)
        self.assertEqual([Path(p).name for p in paths], ['essai.png', 'essai.svg', 'essai.pdf'])
        self.assertTrue(all(Path(p).parent == Path(folder).resolve() for p in paths))   # no extra subfolder
        from matplotlib.image import imread
        height, width = imread(os.path.join(folder, 'essai.png')).shape[:2]
        self.assertAlmostEqual(width / 300 * 2.54, 16.0, delta=0.05)
        self.assertAlmostEqual(height / 300 * 2.54, 9.0, delta=0.05)
        self.assertEqual(ax.get_title(loc='left'), '(a) Essai')
        self.assertIn('1 500', [t.get_text() for t in ax.get_xticklabels()])
        import matplotlib.pyplot as plt
        self.assertEqual(plt.rcParams['font.size'], 8)
        self.assertEqual(plt.rcParams['savefig.dpi'], 300)


@unittest.skipUnless(HAS_MPL, 'matplotlib requis')
class Helpers(unittest.TestCase):
    """Fonctions du style pour les erreurs de figure les plus fréquentes : nombres, profondeur, couches, légende."""

    def setUp(self):
        import matplotlib
        matplotlib.use('Agg')
        self.ns = {}
        exec(STYLE_CODE, self.ns)

    def test_numbers_in_french_without_negative_zero_nor_e_notation(self):
        fr = self.ns['nombre_fr']
        self.assertEqual(fr(-0.0), '0')
        self.assertEqual(fr(0.1 + 0.2), '0,3')
        self.assertEqual(fr(-2500.5), '\u22122\u202f500,5')
        self.assertEqual(fr(1e-05), '10$^{-5}$')
        self.assertEqual(fr(2.5e-06), '2,5\u202f×\u202f10$^{-6}$')
        self.assertEqual(fr(-1e16), '\u221210$^{16}$')

    def test_layers_are_bars_and_a_missing_layer_is_hatched_never_zero(self):
        import math
        fig, ax = self.ns['figure']('colonne')
        vides = self.ns['couches'](ax, ['0', 10, 20, 40], [10, 20, 40, 60], ['2010', None, math.nan, 2.4])
        self.assertEqual(vides, 2)
        bars = ax.patches[:2]
        self.assertEqual([(b.get_y(), b.get_height(), b.get_width()) for b in bars], [(0, 10, 2010), (40, 20, 2.4)])
        bands = [p for p in ax.patches[2:]]
        self.assertEqual(len(bands), 2)
        self.assertTrue(all(p.get_hatch() for p in bands))
        labels = ax.get_legend_handles_labels()[1]
        self.assertEqual(labels, ['Couche non renseignée'])            # one entry, not one per band
        self.assertEqual(self.ns['couches'](ax, [], [], []), 0)

    def test_depth_axis_points_down_and_legend_goes_under_the_panels(self):
        fig, axes = self.ns['figure']('page', ncols=2)
        self.ns['profondeur'](axes[0], 160)
        self.assertEqual(axes[0].get_ylim(), (160, 0))
        self.assertEqual(axes[0].get_ylabel(), 'Profondeur (m)')
        for ax in axes:
            ax.plot([0, 1], [0, 1], label='Oithona')
            ax.legend()
        axes[1].plot([0, 1], [1, 0], label='Calanus')
        self.ns['legende_dessous'](fig)
        self.assertTrue(all(ax.get_legend() is None for ax in axes))
        self.assertEqual([t.get_text() for t in fig.legends[0].get_texts()], ['Oithona', 'Calanus'])

    def test_environment_rules_are_served(self):
        import warehouse_connect
        text = ' '.join(GRAPHICS.values())
        for rule in ('ENVIRONNEMENT', '.venv', 'seule exception à RANGEMENT', 'ne pas l’installer sans accord',
                     'pas de sudo', 'provenance.md', 'install.packages'):
            self.assertIn(rule, text)
        self.assertIn('.venv', warehouse_connect.workspace_text())


def rscript():
    import glob
    import shutil
    found = shutil.which('Rscript') or sorted(glob.glob(r'C:\Program Files\R\R-*\bin\Rscript.exe'))
    return found if isinstance(found, str) else (found[-1] if found else None)


class Clarity(unittest.TestCase):
    def test_clarity_rules_and_r_template_are_served(self):
        from warehouse_context import STYLE_CODE_R
        text = ' '.join(GRAPHICS.values())
        self.assertIn(STYLE_CODE_R, GRAPHICS['purpose'])
        for rule in ('RIEN NE SE SUPERPOSE', 'CHAQUE SÉRIE SE VOIT', 'PAS DE LIEN INVENTÉ', 'TEXTE ENTIER',
                     'GRADUATIONS', 'CADRAGE', 'RELECTURE', 'na.rm = TRUE', 'labels = taxon'):
            self.assertIn(rule, text)
        self.assertIn('enregistrer <- function(p, nom, dossier,', STYLE_CODE_R)   # no default folder either


@unittest.skipUnless(rscript(), 'R requis')
class CopiedAsIsInR(unittest.TestCase):
    def test_the_r_template_saves_three_formats_with_labels_bound_to_entities(self):
        import subprocess
        from warehouse_context import STYLE_CODE_R
        folder = Path(tempfile.mkdtemp())
        script = folder / 'essai.R'
        # Data deliberately not in alphabetical order: labels must follow the entity, not the position.
        script.write_text(STYLE_CODE_R + """
d <- data.frame(z0 = c(0, 20), z1 = c(20, 40), a = c(1500, 30), t = c('Oithona similis', 'Harpacticoida'))
p <- ggplot(d) + geom_rect(aes(xmin = 0, xmax = a, ymin = z0, ymax = z1, fill = t)) + scale_y_reverse() +
  scale_x_continuous(labels = nombre_fr) + scale_fill_manual(values = couleurs(d$t), labels = taxon)
b <- ggplot_build(p)
cat('COULEUR', b$data[[1]]$fill[b$plot$data$t == 'Oithona similis'], '\\n')
cat('LIBELLES', sapply(taxon(c('Oithona similis', 'Pseudocalanus spp.', 'Harpacticoida')), deparse), sep = '|')
cat('\\nNOMBRE', utf8ToInt(nombre_fr(1500)), '|', utf8ToInt(nombre_fr(c(-0.5, 0, 0.5))[1]), '\\n')   # codes: console-proof; ticks as on an axis
invisible(enregistrer(p, 'essai', '""" + folder.as_posix() + """'))
""", encoding='utf-8')
        done = subprocess.run([rscript(), str(script)], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(done.returncode, 0, done.stderr[-500:])
        self.assertIn('COULEUR #2a78d6', done.stdout)            # first entity, first colour, whatever the sort
        self.assertIn('italic("Oithona") ~ italic("similis")', done.stdout)
        self.assertIn('italic("Pseudocalanus") ~ "spp."', done.stdout)
        self.assertIn('"Harpacticoida"', done.stdout)
        # \u00ab 1 500 \u00bb with a narrow no-break space (8239), \u00ab \u22120,5 \u00bb with a true minus (8722) and a decimal comma (44)
        self.assertIn('NOMBRE 49 8239 53 48 48 | 8722 48 44 53', done.stdout)
        for ext in ('png', 'svg', 'pdf'):
            self.assertTrue((folder / f'essai.{ext}').stat().st_size > 0)


@unittest.skipUnless(rscript(), 'R requis')
class HelpersInR(unittest.TestCase):
    def test_depth_points_down_keeps_deep_data_and_missing_layers_are_grey_bands(self):
        import subprocess
        from warehouse_context import STYLE_CODE_R
        folder = Path(tempfile.mkdtemp())
        script = folder / 'aides.R'
        script.write_text(STYLE_CODE_R + """
d <- data.frame(haut = c(0, 10, 20), bas = c(10, 20, 40), valeur = c(2010, NA, 2.4))
p <- ggplot() + couches(d) + profondeur(30)
b <- ggplot_build(p)
cat('COUCHES', nrow(b$data[[1]]), nrow(b$data[[2]]), '\\n')        # 2 bars, 1 grey band
cat('PROFONDEUR', b$layout$panel_params[[1]]$y.range, '\\n')      # reversed scale: -30 to 0
cat('GARDEES', sum(!is.na(b$data[[1]]$ymax)), '\\n')              # the 20-40 m bar beyond 30 m is kept, clipped
""", encoding='utf-8')
        done = subprocess.run([rscript(), str(script)], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(done.returncode, 0, done.stderr[-500:])
        self.assertIn('COUCHES 2 1', done.stdout)
        self.assertIn('PROFONDEUR -30 0', done.stdout)
        self.assertIn('GARDEES 2', done.stdout)


class Tidiness(unittest.TestCase):
    def test_every_question_gets_its_own_folder_never_the_root(self):
        import warehouse_connect
        for text in (warehouse_connect.SERVER_INSTRUCTIONS, warehouse_connect.workspace_text(),
                     ' '.join(GRAPHICS.values())):
            self.assertIn('analyses/', text)
            self.assertIn('racine', text)
        self.assertIn('def enregistrer(fig, nom, dossier):', STYLE_CODE)   # no default: no file lands at the root


class FiletIsCopepods(unittest.TestCase):
    def test_filet_sheets_say_copepods_only_and_list_summed_taxa(self):
        from warehouse_context import VIEWS
        for name in ('filet_data', 'filet_totals'):
            text = ' '.join(VIEWS[name].values())
            for part in ('COPÉPODES SEULEMENT', 'nauplii', 'exclusivité n’est pas documentée', 'Calanus spp.', 'KEBABB'):
                self.assertIn(part, text)


class Principles(unittest.TestCase):
    def test_three_principles_served_once_everywhere(self):
        import warehouse_connect
        from publish_warehouse_context import OVERVIEW
        p = warehouse_connect.PRINCIPLES
        for name in ('1) RÔLE', '2) COMBINAISON', '3) CHOIX', 'ni pour ni contre', 'même définition',
                     'priment sur les cas particuliers'):
            self.assertIn(name, p)
        for text in (warehouse_connect.SERVER_INSTRUCTIONS, warehouse_connect.workspace_text(), OVERVIEW):
            self.assertEqual(text.count(p), 1)


class AnswerRules(unittest.TestCase):
    def test_no_scientific_interpretation_anywhere(self):
        from publish_warehouse_context import OVERVIEW
        text = ' '.join(GRAPHICS.values())
        self.assertIn('AUCUNE INTERPRÉTATION SCIENTIFIQUE', text)
        for scope in ('ni dans la figure, ni dans la légende, ni dans la réponse', 'ni physique, ni causale'):
            self.assertIn(scope, text)
        for word in ('« thermocline »', '« domine »', '« explique »', '« suggère »'):
            self.assertIn(word, text)                                # listed as forbidden
        self.assertIn('principe RÔLE', text)                           # the sheet points to the principle

    def test_data_method_and_limits_template(self):
        text = ' '.join(GRAPHICS.values())
        for part in ('LÉGENDE DE FIGURE', 'DONNÉES :', 'MÉTHODE :', 'LIMITES :', 'STATUT :', 'dataset_version',
                     'formule', 'dénominateur', 'sous le seuil de détection', 'tronqué à 1 000 lignes',
                     'accepted ou candidate', 'jamais des zéros'):
            self.assertIn(part, text)


class BestPractices(unittest.TestCase):
    def test_sources_rules_are_in_the_sheet(self):
        text = ' '.join(GRAPHICS.values())
        for rule in ('une seule question', 'part de zéro', 'jamais d’axe tronqué', 'perceptuellement uniformes',
                     'jamais d’arc-en-ciel', 'divergente centrée sur une valeur de référence',
                     'ne pas colorer par la variable déjà portée par un axe', 'grille d’interpolation',
                     'ne rien tracer au-delà des données', '89 mm', 'PDF', 'Thyng', 'Rougier'):
            self.assertIn(rule, text)


if __name__ == '__main__':
    unittest.main()
