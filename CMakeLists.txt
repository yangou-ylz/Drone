cmake_minimum_required(VERSION 3.20)

project(ANO_LX_STM32F407 C ASM)

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS ON)

set(MCU_FLAGS
  -mcpu=cortex-m4
  -mthumb
  -mfpu=fpv4-sp-d16
  -mfloat-abi=hard
)

add_compile_options(
  ${MCU_FLAGS}
  -ffunction-sections
  -fdata-sections
  -Wall
  -Wextra
  -Wno-unused-parameter
  -Wno-missing-field-initializers
)

add_compile_options(
  $<$<COMPILE_LANGUAGE:C>:-std=gnu99>
)

add_link_options(
  ${MCU_FLAGS}
  -T${CMAKE_SOURCE_DIR}/ProjectSTM32F407/STM32F407VETx_FLASH.ld
  -Wl,-Map=${CMAKE_BINARY_DIR}/ANO_LX.map
  -Wl,--gc-sections
  -Wl,--print-memory-usage
  --specs=nano.specs
  --specs=nosys.specs
)

add_definitions(
  -DSTM32F4XX
  -DUSE_STDPERIPH_DRIVER
  -DUSE_USB_OTG_FS
)

add_executable(ANO_LX.elf
  FcSrc/main.c
  FcSrc/Ano_Scheduler.c
  FcSrc/User_Task.c
  FcSrc/Uplink_Cmd.c
  FcSrc/Auto_Mission.c
  FcSrc/ANO_LX.c
  FcSrc/ANO_DT_LX.c
  FcSrc/LX_FC_EXT_Sensor.c
  FcSrc/LX_FC_Fun.c
  FcSrc/LX_FC_State.c
  FcSrc/Ctrl_PID.c
  DriversBsp/Drv_BSP.c
  DriversBsp/Ano_Math.c
  DriversBsp/Drv_AnoOf.c
  DriversBsp/Drv_UbloxGPS.c
  DriversMcu/STM32F407/Drivers/stm32f4xx_it.c
  DriversMcu/STM32F407/Drivers/Drv_Sys.c
  DriversMcu/STM32F407/Drivers/Drv_adc.c
  DriversMcu/STM32F407/Drivers/Drv_led.c
  DriversMcu/STM32F407/Drivers/Drv_PwmOut.c
  DriversMcu/STM32F407/Drivers/Drv_RcIn.c
  DriversMcu/STM32F407/Drivers/Drv_Timer.c
  DriversMcu/STM32F407/Drivers/Drv_Uart.c
  DriversMcu/STM32F407/Libraries/CMSIS/ST/STM32F4xx/Source/Templates/gcc_ride7/startup_stm32f4xx.s
  DriversMcu/STM32F407/Libraries/CMSIS/ST/STM32F4xx/Source/Templates/system_stm32f4xx.c
  DriversMcu/STM32F407/Libraries/STM32F4xx_StdPeriph_Driver/src/misc.c
  DriversMcu/STM32F407/Libraries/STM32F4xx_StdPeriph_Driver/src/stm32f4xx_adc.c
  DriversMcu/STM32F407/Libraries/STM32F4xx_StdPeriph_Driver/src/stm32f4xx_dma.c
  DriversMcu/STM32F407/Libraries/STM32F4xx_StdPeriph_Driver/src/stm32f4xx_exti.c
  DriversMcu/STM32F407/Libraries/STM32F4xx_StdPeriph_Driver/src/stm32f4xx_flash.c
  DriversMcu/STM32F407/Libraries/STM32F4xx_StdPeriph_Driver/src/stm32f4xx_gpio.c
  DriversMcu/STM32F407/Libraries/STM32F4xx_StdPeriph_Driver/src/stm32f4xx_rcc.c
  DriversMcu/STM32F407/Libraries/STM32F4xx_StdPeriph_Driver/src/stm32f4xx_spi.c
  DriversMcu/STM32F407/Libraries/STM32F4xx_StdPeriph_Driver/src/stm32f4xx_tim.c
  DriversMcu/STM32F407/Libraries/STM32F4xx_StdPeriph_Driver/src/stm32f4xx_usart.c
)

target_include_directories(ANO_LX.elf PRIVATE
  ${CMAKE_SOURCE_DIR}/compat/include
  ${CMAKE_SOURCE_DIR}/ProjectSTM32F407/build
  ${CMAKE_SOURCE_DIR}/FcSrc
  ${CMAKE_SOURCE_DIR}/DriversBsp
  ${CMAKE_SOURCE_DIR}/DriversMcu/STM32F407/Drivers
  ${CMAKE_SOURCE_DIR}/DriversMcu/STM32F407/Libraries/STM32F4xx_StdPeriph_Driver/inc
  ${CMAKE_SOURCE_DIR}/DriversMcu/STM32F407/Libraries/CMSIS/Include
  ${CMAKE_SOURCE_DIR}/DriversMcu/STM32F407/Libraries/CMSIS/ST/STM32F4xx/Include
  ${CMAKE_SOURCE_DIR}/DriversMcu/STM32F407
)

set_target_properties(ANO_LX.elf PROPERTIES
  LINK_DEPENDS ${CMAKE_SOURCE_DIR}/ProjectSTM32F407/STM32F407VETx_FLASH.ld
)

add_custom_command(TARGET ANO_LX.elf POST_BUILD
  COMMAND ${CMAKE_SIZE} $<TARGET_FILE:ANO_LX.elf>
  COMMAND ${CMAKE_OBJCOPY} -O ihex $<TARGET_FILE:ANO_LX.elf> ${CMAKE_BINARY_DIR}/ANO_LX.hex
  COMMAND ${CMAKE_OBJCOPY} -O binary $<TARGET_FILE:ANO_LX.elf> ${CMAKE_BINARY_DIR}/ANO_LX.bin
  BYPRODUCTS ${CMAKE_BINARY_DIR}/ANO_LX.hex ${CMAKE_BINARY_DIR}/ANO_LX.bin
)
