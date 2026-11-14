import "@material/web/ripple/ripple.js";
import "@material/web/focus/md-focus-ring.js";
import { Icon } from "./Icon";
import type { IconName } from "../theme/icons.generated";
import "./shell.css";

export interface Destination<Id extends string> {
  id: Id;
  label: string;
  icon: IconName;
}

interface NavigationRailProps<Id extends string> {
  destinations: ReadonlyArray<Destination<Id>>;
  current: Id;
  onSelect: (id: Id) => void;
}

/** Material 3 navigation rail: the app's top-level destinations, built from M3 tokens. */
export function NavigationRail<Id extends string>({
  destinations,
  current,
  onSelect,
}: NavigationRailProps<Id>) {
  return (
    <nav className="rail" aria-label="Main">
      <div className="rail-brand" aria-hidden="true">
        <Icon name="headphones" filled size={28} />
      </div>
      <ul className="rail-items">
        {destinations.map((item) => {
          const active = item.id === current;
          return (
            <li key={item.id}>
              <button
                type="button"
                className="rail-item"
                aria-current={active ? "page" : undefined}
                onClick={() => onSelect(item.id)}
              >
                <span className="rail-indicator">
                  <md-ripple />
                  <md-focus-ring />
                  <Icon name={item.icon} filled={active} />
                </span>
                <span className="rail-label">{item.label}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
