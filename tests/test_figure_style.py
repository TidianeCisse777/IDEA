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
