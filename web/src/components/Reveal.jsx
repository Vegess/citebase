import { useReveal } from "../hooks/motion";

/** Wraps content in an element that fades and rises in once, the first time it scrolls into view. */
export function Reveal({ as: Tag = "div", className = "", delay = 0, style, children, ...rest }) {
  const ref = useReveal();
  return (
    <Tag ref={ref} className={`reveal ${className}`} style={delay ? { ...style, transitionDelay: `${delay}ms` } : style} {...rest}>
      {children}
    </Tag>
  );
}
