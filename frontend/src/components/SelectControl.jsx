import { useEffect, useRef, useState } from 'react'

function SelectControl({ id, labelId, value, options, onChange }) {
  const [isOpen, setIsOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(0)
  const rootRef = useRef(null)
  const triggerRef = useRef(null)
  const selectedIndex = options.findIndex((option) => option.value === value)
  const listboxId = `${id}-options`

  function open() {
    setActiveIndex(selectedIndex < 0 ? 0 : selectedIndex)
    setIsOpen(true)
  }

  function select(index) {
    const option = options[index]
    if (!option) return
    onChange(option.value)
    setActiveIndex(index)
    setIsOpen(false)
    triggerRef.current?.focus()
  }

  useEffect(() => {
    if (!isOpen) return undefined

    function closeOnOutsidePointer(event) {
      if (!rootRef.current?.contains(event.target)) setIsOpen(false)
    }

    document.addEventListener('pointerdown', closeOnOutsidePointer)
    return () => document.removeEventListener('pointerdown', closeOnOutsidePointer)
  }, [isOpen])

  function handleKeyDown(event) {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      if (!isOpen) {
        open()
        return
      }
      const direction = event.key === 'ArrowDown' ? 1 : -1
      setActiveIndex((index) => (index + direction + options.length) % options.length)
    } else if (event.key === 'Home' && isOpen) {
      event.preventDefault()
      setActiveIndex(0)
    } else if (event.key === 'End' && isOpen) {
      event.preventDefault()
      setActiveIndex(options.length - 1)
    } else if (event.key === 'Enter') {
      event.preventDefault()
      if (isOpen) select(activeIndex)
      else open()
    } else if (event.key === ' ' && isOpen) {
      event.preventDefault()
      select(activeIndex)
    } else if (event.key === 'Tab' && isOpen) {
      setIsOpen(false)
    } else if (event.key === 'Escape' && isOpen) {
      event.preventDefault()
      setIsOpen(false)
    }
  }

  const currentOption = options[selectedIndex]

  return (
    <div className="select-control" ref={rootRef}>
      <button
        ref={triggerRef}
        className="select-control__trigger"
        id={id}
        type="button"
        role="combobox"
        aria-labelledby={`${labelId} ${id}-value`}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-controls={listboxId}
        aria-activedescendant={isOpen ? `${id}-option-${activeIndex}` : undefined}
        onClick={() => (isOpen ? setIsOpen(false) : open())}
        onKeyDown={handleKeyDown}
      >
        <span id={`${id}-value`}>{currentOption?.label ?? ''}</span>
        <span className="select-control__chevron" aria-hidden="true" />
      </button>
      <ul
        className="select-control__options"
        id={listboxId}
        role="listbox"
        aria-labelledby={labelId}
        hidden={!isOpen}
      >
        {options.map((option, index) => (
          <li
            className="select-control__option"
            id={`${id}-option-${index}`}
            key={option.value}
            role="option"
            aria-selected={index === selectedIndex}
            data-active={index === activeIndex}
            onMouseDown={(event) => event.preventDefault()}
            onMouseEnter={() => setActiveIndex(index)}
            onClick={() => select(index)}
          >
            {option.label}
          </li>
        ))}
      </ul>
    </div>
  )
}

export default SelectControl
