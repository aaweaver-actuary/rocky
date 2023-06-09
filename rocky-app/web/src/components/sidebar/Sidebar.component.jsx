import { useState, useEffect } from 'react';
import PropTypes from 'prop-types';

import SidebarToggle from './sub-components/SidebarToggle.component';
import SidebarMenu from './sub-components/SidebarMenu.component';

const MOUSE_EXIT_TIMEOUT = 10000;

const Sidebar = ({
	isSidebarExpanded,
	setIsSidebarExpanded,
	onAddLoadDataWindow,
	onClickNew,
}) => {
	const [activeAccordion, setActiveAccordion] = useState(null);
	const [timeoutId, setTimeoutId] = useState(null);

	// when mouse enters sidebar, if it is collapsed, expand it
	const expandSidebar = () => {
		setIsSidebarExpanded(true);
	};

	// when mouse leaves sidebar, start countdown to collapse sidebar
	const startCountdown = () => {
		if (isSidebarExpanded) {
			const id = setTimeout(() => {
				setIsSidebarExpanded(false);
				setActiveAccordion(null);
			}, MOUSE_EXIT_TIMEOUT);
			setTimeoutId(id);
		}
	};

	// if mouse re-enters sidebar, cancel countdown
	const cancelCountdown = () => {
		if (timeoutId) {
			clearTimeout(timeoutId);
			setTimeoutId(null);
		}
	};

	// check timeoutId each time it changes, and if it equals
	// MOUSE_EXIT_TIMEOUT, clear it
	useEffect(() => {
		return () => {
			if (timeoutId) {
				clearTimeout(timeoutId);
			}
		};
	}, [timeoutId]);

	// toggle sidebar between expanded and collapsed
	const toggleSidebar = () => {
		setIsSidebarExpanded(!isSidebarExpanded);
		setActiveAccordion(null);
	};

	// toggle accordion between expanded and collapsed
	const toggleAccordion = (index) => {
		if (activeAccordion === index) {
			setActiveAccordion(null);
		} else {
			setActiveAccordion(index);
			setIsSidebarExpanded(true);
		}
	};

	// handle click on accordion item
	const handleClickItem = (item) => {
		// NEW
		if (item === 'New') {
			onClickNew();
		}

		// LOAD DATA
		else if (item === 'Sample Data') {
			onAddLoadDataWindow('Sample Data');
		} else if (item === 'Clipboard') {
			onAddLoadDataWindow('Clipboard');
		} else if (item === 'Excel') {
			onAddLoadDataWindow('Excel');
		} else if (item === 'CSV') {
			onAddLoadDataWindow('CSV');
		}

		// MODEL SELECTION
		// else if (item === 'Chain Ladder') { }
		// else if (item === 'GLM') { }
		// else if (item === 'MegaModel') { }

		// Add conditions for other items here
	};

	// if mouse enters sidebar, expand it if needed, and cancel
	// countdown if it is going
	const handleMouseEnter = () => {
		if (!isSidebarExpanded) {
			expandSidebar();
		}
		cancelCountdown();
	};

	return (
		<div
			className={`sidebar ${isSidebarExpanded ? 'expanded' : 'collapsed'}`}
			onMouseLeave={startCountdown}
			onMouseEnter={handleMouseEnter}
		>
			<SidebarToggle
				isSidebarExpanded={isSidebarExpanded}
				toggleSidebar={toggleSidebar}
			/>
			<SidebarMenu
				activeAccordion={activeAccordion}
				toggleAccordion={toggleAccordion}
				handleClickItem={handleClickItem}
				isSidebarExpanded={isSidebarExpanded}
				onAddLoadDataWindow={onAddLoadDataWindow}
				onClickNew={onClickNew}
			/>
		</div>
	);
};
Sidebar.propTypes = {
	isSidebarExpanded: PropTypes.bool,
	setIsSidebarExpanded: PropTypes.func,
	onAddLoadDataWindow: PropTypes.func,
	onClickNew: PropTypes.func,
	onToggleAccordion: PropTypes.func,
	onClickItem: PropTypes.func,
};

export default Sidebar;
