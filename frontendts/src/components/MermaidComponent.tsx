// Copyright Bunting Labs, Inc. 2025

import React from "react";
import mermaid from "mermaid";

mermaid.initialize({
  startOnLoad: true,
  theme: "dark",
  securityLevel: "loose",
  fontFamily: "Fira Code"
});

interface MermaidProps {
  chart: string;
}

export default class MermaidComponent extends React.Component<MermaidProps> {
  componentDidMount() {
    console.log('Mermaid componentDidMount called');
    mermaid.contentLoaded();
  }

  render() {
    console.log('Mermaid render called with chart:', this.props.chart.substring(0, 100));
    return <div className="mermaid">{this.props.chart}</div>;
  }
}