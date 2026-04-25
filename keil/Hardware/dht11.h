#ifndef __DHT11_H
#define __DHT11_H
#include "stm32f10x.h"

// 第一个 DHT11（你原来的）
#define DHT11_1_PORT    GPIOB
#define DHT11_1_PIN     GPIO_Pin_15
#define DHT11_1_RCC     RCC_APB2Periph_GPIOB

// 第二个 DHT11（新增，你可以自己改引脚）
#define DHT11_2_PORT    GPIOB
#define DHT11_2_PIN     GPIO_Pin_14
#define DHT11_2_RCC     RCC_APB2Periph_GPIOB

// 函数全部改为带端口+引脚参数，通用驱动
void DHT11_IO_OUT(GPIO_TypeDef* GPIOx, uint16_t GPIO_Pin);
void DHT11_IO_IN(GPIO_TypeDef* GPIOx, uint16_t GPIO_Pin);
void DHT11_RST(GPIO_TypeDef* GPIOx, uint16_t GPIO_Pin);
u8 DHT11_Check(GPIO_TypeDef* GPIOx, uint16_t GPIO_Pin);

u8 DHT11_Init(GPIO_TypeDef* GPIOx, uint16_t GPIO_Pin, uint32_t GPIO_RCC);
u8 DHT11_Read_Data(GPIO_TypeDef* GPIOx, uint16_t GPIO_Pin, u8 *temp, u8 *humi);

#endif

