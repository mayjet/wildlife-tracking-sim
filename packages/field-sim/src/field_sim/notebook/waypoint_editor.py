from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

import matplotlib.pyplot as plt
import numpy as np
from IPython.display import display
from ipywidgets import Button, Dropdown, HBox, HTML, Output, Text, ToggleButtons, VBox

from field_environment import EnvironmentCase, plot_experiment_environment

from ..route_generators import generate_resolved_route
from ..route_planning import resolve_waypoint_position
from ..routes import ResolvedRoute, RouteDefinition
from ..waypoints import (
    WaypointSet,
    WaypointSpec,
    load_waypoint_set,
    save_waypoint_set,
    validate_waypoint_set,
)


class WaypointEditor:
    """Notebook UI for editing one ordered WaypointSet on the complete Case map."""

    def __init__(
        self,
        environment_case: EnvironmentCase,
        *,
        waypoint_set_id: str,
        save_path: str | Path | None = None,
        initial: WaypointSet | None = None,
        route_methods: Sequence[str] = ("smooth", "meandering"),
        route_settings: Mapping[str, Mapping[str, object]] | None = None,
        route_seed: int = 42,
    ) -> None:
        self.environment_case = environment_case
        self.waypoint_set_id = waypoint_set_id
        self.save_path = None if save_path is None else Path(save_path)
        self.route_methods = tuple(route_methods)
        self.route_settings = {
            method: dict(parameters)
            for method, parameters in (route_settings or {}).items()
        }
        self.route_seed = route_seed
        self._points: list[tuple[float, float, float]] = []
        self._history: list[list[tuple[float, float, float]]] = []
        self._move_index: int | None = None
        self._routes: dict[str, ResolvedRoute] = {}
        self._notice = ""
        with plt.ioff():
            self.figure, self.axis = plot_experiment_environment(environment_case)
        self._draw_traversability_overlay()
        self.axis.set_title("Waypoint editor — full acquired terrain extent")
        self._mode = ToggleButtons(
            options=(("追加", "add"), ("移動", "move"), ("削除", "delete")),
            value="add",
            description="操作",
        )
        self._status = HTML()
        self._output = Output()
        self._undo = Button(description="元に戻す")
        self._clear = Button(description="全消去")
        self._point_selector = Dropdown(description="Waypoint", options=())
        self._move_up = Button(description="順序を上へ")
        self._move_down = Button(description="順序を下へ")
        self._validate = Button(description="検証")
        self._save = Button(description="YAML保存", button_style="success")
        self._route_buttons = []
        for method in self.route_methods:
            button = Button(description=f"{method}表示")
            button.on_click(lambda _, selected=method: self.preview_route(selected))
            self._route_buttons.append(button)
        self._undo.on_click(lambda _: self.undo())
        self._clear.on_click(lambda _: self.clear())
        self._move_up.on_click(lambda _: self.move_selected(-1))
        self._move_down.on_click(lambda _: self.move_selected(1))
        self._validate.on_click(lambda _: self.validate())
        self._save.on_click(lambda _: self.save(overwrite=True))
        self.figure.canvas.mpl_connect("button_press_event", self._on_click)
        self.set_waypoint_set(waypoint_set_id, initial=initial)

    def _planning_parameters(self) -> dict[str, object]:
        parameters: dict[str, object] = {}
        for method in self.route_methods:
            parameters.update(self.route_settings.get(method, {}))
        return parameters

    def _draw_traversability_overlay(self) -> None:
        traversability = self.environment_case.traversability
        if traversability is None:
            return
        bounds = traversability.grid.bounds
        extent = (bounds.min_x_m, bounds.max_x_m, bounds.min_y_m, bounds.max_y_m)
        prohibited = np.where(traversability.values == 3, 1.0, np.nan)
        difficult = np.where(traversability.values == 2, 1.0, np.nan)
        self.axis.imshow(
            difficult,
            origin="lower",
            extent=extent,
            cmap="Oranges",
            vmin=0.0,
            vmax=1.0,
            alpha=0.35,
            interpolation="nearest",
        )
        self.axis.imshow(
            prohibited,
            origin="lower",
            extent=extent,
            cmap="Reds",
            vmin=0.0,
            vmax=1.0,
            alpha=0.65,
            interpolation="nearest",
        )

    def _resolved_click(self, x_m: float, y_m: float) -> tuple[float, float]:
        adjustment = resolve_waypoint_position(
            self.environment_case,
            x_m,
            y_m,
            parameters=self._planning_parameters(),
            waypoint_id=f"WP{len(self._points) + 1:03d}",
        )
        if adjustment.reason is not None:
            self._notice = (
                f"禁止地点から{adjustment.distance_m:.1f} m補正した: "
                f"({adjustment.resolved_x_m:.1f}, {adjustment.resolved_y_m:.1f})"
            )
        else:
            self._notice = ""
        return adjustment.resolved_x_m, adjustment.resolved_y_m

    def _snapshot(self) -> None:
        self._history.append(list(self._points))

    def _nearest_index(self, x_m: float, y_m: float) -> int | None:
        if not self._points:
            return None
        distances = [(x - x_m) ** 2 + (y - y_m) ** 2 for x, y, _ in self._points]
        return min(range(len(distances)), key=distances.__getitem__)

    def _on_click(self, event) -> None:
        if event.inaxes is not self.axis or event.xdata is None or event.ydata is None:
            return
        x_m, y_m = float(event.xdata), float(event.ydata)
        mode = self._mode.value
        if mode == "add":
            try:
                x_m, y_m = self._resolved_click(x_m, y_m)
            except ValueError as error:
                self._status.value = str(error)
                return
            self._snapshot()
            self._points.append((x_m, y_m, 0.0))
        elif mode == "delete":
            index = self._nearest_index(x_m, y_m)
            if index is not None:
                self._snapshot()
                self._points.pop(index)
        elif self._move_index is None:
            self._move_index = self._nearest_index(x_m, y_m)
            self._status.value = "移動するWaypointを選択した．移動先をクリックする．"
            return
        else:
            try:
                x_m, y_m = self._resolved_click(x_m, y_m)
            except ValueError as error:
                self._status.value = str(error)
                return
            self._snapshot()
            _, _, dwell_s = self._points[self._move_index]
            self._points[self._move_index] = (x_m, y_m, dwell_s)
            self._move_index = None
        self._routes.clear()
        self._refresh()

    def set_waypoint_set(
        self,
        waypoint_set_id: str,
        *,
        initial: WaypointSet | None = None,
    ) -> None:
        if initial is not None and initial.case_id != self.environment_case.case_spec.case_id:
            raise ValueError("WaypointSet.case_id does not match the loaded Case")
        self.waypoint_set_id = waypoint_set_id
        self._points = [] if initial is None else [
            (point.x_m, point.y_m, point.dwell_s) for point in initial.waypoints
        ]
        self._history.clear()
        self._move_index = None
        self._routes.clear()
        self._notice = ""
        self._refresh()

    def get_waypoint_set(self) -> WaypointSet:
        return WaypointSet(
            waypoint_set_id=self.waypoint_set_id,
            case_id=self.environment_case.case_spec.case_id,
            waypoints=tuple(
                WaypointSpec(
                    id=f"WP{index + 1:03d}", x_m=x_m, y_m=y_m, dwell_s=dwell_s
                )
                for index, (x_m, y_m, dwell_s) in enumerate(self._points)
            ),
        )

    def _refresh(self) -> None:
        for artist in list(self.axis.lines):
            if artist.get_gid() == "waypoint-editor":
                artist.remove()
        for text in list(self.axis.texts):
            if text.get_gid() == "waypoint-editor":
                text.remove()
        if self._points:
            x_values = [point[0] for point in self._points]
            y_values = [point[1] for point in self._points]
            line = self.axis.plot(
                x_values,
                y_values,
                color="deepskyblue",
                marker="o",
                linewidth=1.5,
                label="Waypoints",
            )[0]
            line.set_gid("waypoint-editor")
            for index, (x_m, y_m, _) in enumerate(self._points):
                label = self.axis.text(x_m, y_m, f"WP{index + 1:03d}", color="white")
                label.set_gid("waypoint-editor")
        route_colors = {
            "direct": "dodgerblue",
            "smooth": "cyan",
            "meandering": "magenta",
        }
        for method, route in self._routes.items():
            line = self.axis.plot(
                route.points["x_m"],
                route.points["y_m"],
                color=route_colors.get(method, "yellow"),
                linewidth=2.0,
                label=method,
            )[0]
            line.set_gid("waypoint-editor")
        selected_index = self._point_selector.value
        self._point_selector.options = tuple(
            (f"WP{index + 1:03d}", index) for index in range(len(self._points))
        )
        if selected_index is not None and selected_index < len(self._points):
            self._point_selector.value = selected_index
        self.figure.canvas.draw_idle()
        self._status.value = (
            f"編集中: {self.waypoint_set_id} ／ Waypoint数: {len(self._points)}"
            + (f"<br>{self._notice}" if self._notice else "")
        )

    def undo(self) -> None:
        if self._history:
            self._points = self._history.pop()
            self._routes.clear()
            self._refresh()

    def clear(self) -> None:
        if self._points:
            self._snapshot()
            self._points.clear()
            self._routes.clear()
            self._refresh()

    def move_selected(self, offset: int) -> None:
        index = self._point_selector.value
        if index is None:
            return
        destination = index + offset
        if destination < 0 or destination >= len(self._points):
            return
        self._snapshot()
        point = self._points.pop(index)
        self._points.insert(destination, point)
        self._routes.clear()
        self._refresh()
        self._point_selector.value = destination

    def preview_route(self, method: str) -> ResolvedRoute | None:
        with self._output:
            self._output.clear_output()
            try:
                route = self._generate_route(method)
                self._routes[method] = route
                print(
                    f"{method}: {route.length_m:.1f} m，"
                    f"詳細点 {len(route.points)}，警告 {len(route.warnings)}件"
                )
                for warning in route.warnings:
                    print(f"- {warning}")
                self._refresh()
                return route
            except Exception as error:
                print(f"生成失敗: {type(error).__name__}: {error}")
                return None

    def _generate_route(self, method: str) -> ResolvedRoute:
        waypoint_set = self.get_waypoint_set()
        parameters = dict(self.route_settings.get(method, {}))
        parameters.setdefault("point_spacing_m", 1.0)
        if method in {"smooth", "meandering"}:
            parameters.setdefault("smoothing_tension", 0.0)
        if method == "meandering":
            parameters.setdefault("max_lateral_offset_m", 15.0)
            parameters.setdefault("meander_interval_m", 30.0)
        definition = RouteDefinition(
            route_id=f"{self.waypoint_set_id}-{method}-draft",
            route_group_id=self.waypoint_set_id,
            method=method,
            waypoint_set="draft",
            seed=int(parameters.pop("seed", self.route_seed)),
            parameters=parameters,
        )
        return generate_resolved_route(
            self.environment_case,
            definition,
            waypoint_set,
        )

    def validate_routes(self) -> bool:
        valid = True
        generated = {}
        with self._output:
            self._output.clear_output()
            for method in self.route_methods:
                try:
                    route = self._generate_route(method)
                    generated[method] = route
                    print(f"{method}: OK — {route.length_m:.1f} m")
                except Exception as error:
                    valid = False
                    print(f"{method}: NG — {type(error).__name__}: {error}")
        self._routes = generated
        self._refresh()
        return valid

    def preview_all_routes(self) -> dict[str, ResolvedRoute]:
        for method in self.route_methods:
            self.preview_route(method)
        return dict(self._routes)

    def validate(self) -> tuple[str, ...] | None:
        with self._output:
            self._output.clear_output()
            try:
                warnings = validate_waypoint_set(
                    self.environment_case, self.get_waypoint_set()
                )
                print("Waypoint検証: OK")
                for warning in warnings:
                    print(f"- {warning}")
                return warnings
            except Exception as error:
                print(f"Waypoint検証: NG — {type(error).__name__}: {error}")
                return None

    def save(self, path: str | Path | None = None, *, overwrite: bool = False) -> Path | None:
        destination = self.save_path if path is None else Path(path)
        with self._output:
            self._output.clear_output()
            if destination is None:
                print("保存先が未指定である．save_pathまたはpathを指定すること．")
                return None
            try:
                waypoint_set = self.get_waypoint_set()
                validate_waypoint_set(self.environment_case, waypoint_set)
                if not self.validate_routes():
                    return None
                saved = save_waypoint_set(destination, waypoint_set, overwrite=overwrite)
                print(f"Waypointを保存した: {saved}")
                return saved
            except Exception as error:
                print(f"保存失敗: {type(error).__name__}: {error}")
                return None

    def widget(self, *, include_save: bool = True) -> VBox:
        final_controls = [self._validate]
        if include_save:
            final_controls.append(self._save)
        controls = HBox(
            [self._mode, self._undo, self._clear, *self._route_buttons, *final_controls]
        )
        order_controls = HBox([self._point_selector, self._move_up, self._move_down])
        return VBox([controls, order_controls, self._status, self.figure.canvas, self._output])

    def display(self):
        widget = self.widget()
        display(widget)
        return widget


class WaypointSetManager:
    """Notebook UI for creating and persisting any number of WaypointSets."""

    def __init__(
        self,
        environment_case: EnvironmentCase,
        *,
        storage_directory: str | Path,
        required_count: int = 1,
        route_methods: Sequence[str] = ("smooth", "meandering"),
        route_settings: Mapping[str, Mapping[str, object]] | None = None,
        route_seed: int = 42,
        initial_sets: Sequence[WaypointSet] = (),
    ) -> None:
        if required_count <= 0:
            raise ValueError("required_count must be positive")
        self.environment_case = environment_case
        self.storage_directory = Path(storage_directory).expanduser().resolve()
        self.required_count = required_count
        self._sets: dict[str, WaypointSet] = {}
        for path in sorted(self.storage_directory.glob("*.yaml")):
            waypoint_set, _ = load_waypoint_set(path)
            if waypoint_set.case_id == environment_case.case_spec.case_id:
                self._sets[waypoint_set.waypoint_set_id] = waypoint_set
        for waypoint_set in initial_sets:
            if waypoint_set.case_id != environment_case.case_spec.case_id:
                raise ValueError("initial WaypointSet.case_id does not match the loaded Case")
            self._sets.setdefault(waypoint_set.waypoint_set_id, waypoint_set)

        first_id = next(iter(self._sets), self._suggest_id())
        self._selector = Dropdown(description="保存済み", options=())
        self._identifier = Text(description="Set ID", value=first_id)
        self._new = Button(description="新規")
        self._duplicate = Button(description="複製")
        self._save = Button(description="Setを保存", button_style="success")
        self._delete = Button(description="Setを削除", button_style="danger")
        self._status = HTML()
        self.editor = WaypointEditor(
            environment_case,
            waypoint_set_id=first_id,
            initial=self._sets.get(first_id),
            route_methods=route_methods,
            route_settings=route_settings,
            route_seed=route_seed,
        )
        self._new.on_click(lambda _: self.new())
        self._duplicate.on_click(lambda _: self.duplicate())
        self._save.on_click(lambda _: self.save_current())
        self._delete.on_click(lambda _: self.delete_current())
        self._selector.observe(self._on_select, names="value")
        self._refresh_selector(select=first_id if first_id in self._sets else None)

    def _suggest_id(self) -> str:
        index = 1
        while f"route-{index:03d}-v1" in self._sets:
            index += 1
        return f"route-{index:03d}-v1"

    def _refresh_selector(self, *, select: str | None = None) -> None:
        options = tuple(sorted(self._sets))
        self._selector.options = options
        if select in self._sets:
            self._selector.value = select
        self._status.value = (
            f"保存済みWaypoint Set: {len(self._sets)}件 ／ "
            f"今回の目標: {self.required_count}件"
        )

    def _on_select(self, change) -> None:
        selected = change.get("new")
        if not selected or selected not in self._sets:
            return
        self._identifier.value = selected
        self.editor.save_path = self.storage_directory / f"{selected}.yaml"
        self.editor.set_waypoint_set(selected, initial=self._sets[selected])

    def new(self) -> None:
        identifier = self._suggest_id()
        self._identifier.value = identifier
        self.editor.save_path = self.storage_directory / f"{identifier}.yaml"
        self.editor.set_waypoint_set(identifier)

    def duplicate(self) -> None:
        try:
            source = self.editor.get_waypoint_set()
        except Exception:
            return
        identifier = self._suggest_id()
        duplicate = source.model_copy(update={"waypoint_set_id": identifier})
        self._identifier.value = identifier
        self.editor.save_path = self.storage_directory / f"{identifier}.yaml"
        self.editor.set_waypoint_set(identifier, initial=duplicate)

    def save_current(self) -> Path | None:
        identifier = self._identifier.value.strip()
        if not identifier:
            self._status.value = "Waypoint Set IDを入力すること．"
            return None
        self.editor.waypoint_set_id = identifier
        destination = self.storage_directory / f"{identifier}.yaml"
        saved = self.editor.save(destination, overwrite=True)
        if saved is None:
            return None
        waypoint_set, _ = load_waypoint_set(saved)
        self._sets[identifier] = waypoint_set
        self.editor.save_path = destination
        self._refresh_selector(select=identifier)
        return saved

    def delete_current(self) -> None:
        identifier = self._selector.value
        if not identifier or identifier not in self._sets:
            return
        path = self.storage_directory / f"{identifier}.yaml"
        path.unlink(missing_ok=True)
        del self._sets[identifier]
        if self._sets:
            next_id = sorted(self._sets)[0]
            self._refresh_selector(select=next_id)
            self._on_select({"new": next_id})
        else:
            self._refresh_selector()
            self.new()

    def get_waypoint_sets(self, *, require_count: int | None = None) -> tuple[WaypointSet, ...]:
        minimum = self.required_count if require_count is None else require_count
        if len(self._sets) < minimum:
            raise ValueError(
                f"Waypoint Setが不足している: 保存済み{len(self._sets)}件，必要{minimum}件"
            )
        return tuple(self._sets[identifier] for identifier in sorted(self._sets))

    def display(self):
        management = HBox(
            [
                self._selector,
                self._identifier,
                self._new,
                self._duplicate,
                self._save,
                self._delete,
            ]
        )
        widget = VBox([management, self._status, self.editor.widget(include_save=False)])
        display(widget)
        return widget
