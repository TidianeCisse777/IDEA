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
        from matplotlib.image import imread
        height, width = imread(os.path.join(folder, 'essai', 'essai.png')).shape[:2]
        self.assertAlmostEqual(width / 300 * 2.54, 16.0, delta=0.05)
        self.assertAlmostEqual(height / 300 * 2.54, 9.0, delta=0.05)
        self.assertEqual(ax.get_title(loc='left'), '(a) Essai')
        self.assertIn('1 500', [t.get_text() for t in ax.get_xticklabels()])
        import matplotlib.pyplot as plt
        self.assertEqual(plt.rcParams['font.size'], 8)
        self.assertEqual(plt.rcParams['savefig.dpi'], 300)



class AnswerRules(unittest.TestCase):
    def test_no_scientific_interpretation_anywhere(self):
        from publish_warehouse_context import OVERVIEW
        text = ' '.join(GRAPHICS.values())
        self.assertIn('AUCUNE INTERPRÉTATION SCIENTIFIQUE', text)
        for scope in ('ni dans la figure, ni dans la légende, ni dans la réponse', 'ni physique, ni causale'):
            self.assertIn(scope, text)
        for word in ('« thermocline »', '« domine »', '« explique »', '« suggère »'):
            self.assertIn(word, text)                                # listed as forbidden
        self.assertIn('Aucune interprétation scientifique', OVERVIEW)

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
