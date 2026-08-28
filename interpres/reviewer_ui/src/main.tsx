import { render } from 'preact';
import { App } from './app/App';
import '@awesome.me/webawesome/dist/styles/webawesome.css';
import '@awesome.me/webawesome/dist/components/drawer/drawer.js';
import './styles/global.css';

render(<App />, document.getElementById('app')!);
