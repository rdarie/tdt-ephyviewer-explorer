"""A probe-layout electrode-impedance heatmap viewer."""
from __future__ import annotations

from typing import Any

import numpy as np
import pyqtgraph as pg
from ephyviewer.base import ViewerBase
from ephyviewer.myqt import QT


class ImpedanceViewer(ViewerBase):
    """Heatmap of per-contact impedance, laid out in probe topology.

    Impedance is a per-block property rather than a signal, so :meth:`seek` is
    inert and the source exposes no ``t_start`` — which is what keeps
    ``MainViewer`` from widening the navigation range for this dock.

    The source is duck-typed (see :class:`~impedance.ImpedanceGridSource`): it must
    expose ``name``, ``units``, ``frequencies``, ``grids``, ``fields``, and
    ``metadata``.
    """

    _default_params = [
        {"name": "vmin", "type": "float", "value": 0.0},
        {"name": "vmax", "type": "float", "value": 200.0},
        {"name": "annotate", "type": "bool", "value": True},
        {"name": "annotation_format", "type": "str", "value": "R{channel}\n{impedance:.0f}"},
        {"name": "cmap", "type": "str", "value": "viridis"},
    ]

    def __init__(self, **kargs: Any) -> None:
        """Build the heatmap, frequency selector, and metadata footer.

        :param kargs: Passed to :class:`~ephyviewer.base.ViewerBase` (``name``,
            ``source``).
        """
        ViewerBase.__init__(self, **kargs)

        self.params = pg.parametertree.Parameter.create(
            name="Global options", type="group", children=self._default_params
        )

        self.mainlayout = QT.QVBoxLayout()
        self.setLayout(self.mainlayout)

        self.combo_freq = QT.QComboBox()
        for frequency in self.source.frequencies:
            self.combo_freq.addItem("all" if frequency is None else f"{frequency:g} Hz")
        self.combo_freq.setVisible(len(self.source.frequencies) > 1)
        self.mainlayout.addWidget(self.combo_freq)

        self.graphicsview = pg.GraphicsView()
        self.mainlayout.addWidget(self.graphicsview)
        self.plot = pg.PlotItem()
        self.plot.hideButtons()
        self.plot.setAspectLocked(True)
        self.plot.invertY(True)  # grid row 0 renders at the top
        self.graphicsview.setCentralItem(self.plot)

        self.image = pg.ImageItem()
        self.plot.addItem(self.image)
        # Give the bar real levels and a colormap up front: it is attached before the
        # first refresh, when the ImageItem still holds no data to derive them from.
        self.colorbar = pg.ColorBarItem(
            values=(float(self.params["vmin"]), float(self.params["vmax"])),
            colorMap=pg.colormap.getFromMatplotlib(str(self.params["cmap"])),
            label=self.source.units,
            interactive=False,
        )
        self.colorbar.setImageItem(self.image, insert_in=self.plot)

        self.footer = QT.QLabel("")
        self.mainlayout.addWidget(self.footer)

        self._texts: list[pg.TextItem] = []
        self.refresh()

        self.params.sigTreeStateChanged.connect(self._on_change)
        self.combo_freq.currentIndexChanged.connect(self._on_change)

    def _on_change(self, *args: Any) -> None:
        """Re-render after a parameter edit or a frequency change.

        Both signals carry arguments that :meth:`refresh` does not take, hence
        this adapter.
        """
        self.refresh()

    def refresh(self) -> None:
        """Redraw the heatmap for the selected frequency and current params.

        :raises ValueError: If ``vmax`` does not exceed ``vmin``, or ``cmap`` is
            not a known matplotlib colormap.
        """
        index = max(self.combo_freq.currentIndex(), 0)
        grid = self.source.grids[index]
        vmin, vmax = float(self.params["vmin"]), float(self.params["vmax"])
        if vmax <= vmin:
            raise ValueError(
                f"impedance viewer vmax ({vmax:g}) must exceed vmin ({vmin:g})"
            )
        colormap = pg.colormap.getFromMatplotlib(str(self.params["cmap"]))
        self.image.setImage(grid.T, levels=(vmin, vmax))  # ImageItem axis 0 is x
        self.image.setColorMap(colormap)
        self.colorbar.setColorMap(colormap)
        self.colorbar.setLevels((vmin, vmax))
        self._refresh_annotations(grid, vmin, vmax, colormap)
        self._refresh_footer(index)
        self.plot.setRange(
            xRange=(0, grid.shape[1]), yRange=(0, grid.shape[0]), padding=0.02
        )

    def _refresh_annotations(
        self, grid: np.ndarray, vmin: float, vmax: float, colormap: Any
    ) -> None:
        """Rebuild the per-cell numeric labels.

        Empty (NaN) cells are skipped. Text is dark on light cells and light on
        dark ones, by Rec. 709 luminance, so it stays legible at both ends of the
        colormap.

        :param grid: The ``(n_rows, n_cols)`` values being displayed.
        :param vmin: Lower colour level.
        :param vmax: Upper colour level.
        :param colormap: The active pyqtgraph colormap.
        """
        for item in self._texts:
            self.plot.removeItem(item)
        self._texts.clear()
        if not self.params["annotate"]:
            return
        from tdt_ephyviewer_explorer.impedance import format_cell

        template = str(self.params["annotation_format"])
        for row in range(grid.shape[0]):
            for col in range(grid.shape[1]):
                value = grid[row, col]
                if np.isnan(value):
                    continue
                fields = self.source.fields[row, col] or {}
                text = format_cell(template, {**fields, "impedance": float(value)})
                if not text.strip():
                    continue
                fraction = float(np.clip((value - vmin) / (vmax - vmin), 0.0, 1.0))
                red, green, blue = colormap.map(fraction, mode="float")[:3]
                luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
                item = pg.TextItem(
                    text, color="k" if luminance > 0.5 else "w", anchor=(0.5, 0.5)
                )
                item.setPos(col + 0.5, row + 0.5)
                self.plot.addItem(item)
                self._texts.append(item)

    def _refresh_footer(self, index: int) -> None:
        """Show the source name, frequency, and averaged metadata columns.

        This is where non-channel columns such as ``REF (kOhm)`` surface, since
        they are not grid cells.

        :param index: The selected frequency index.
        """
        parts = [self.source.name]
        frequency = self.source.frequencies[index]
        if frequency is not None:
            parts.append(f"{frequency:g} Hz")
        parts += [
            f"{key}: {value:g}"
            for key, value in sorted(self.source.metadata[index].items())
            if not np.isnan(value)
        ]
        self.footer.setText("   |   ".join(parts))
