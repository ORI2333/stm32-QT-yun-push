
#ifndef __Periph_GPIO_Init_H
#define __Periph_GPIO_Init_H

void Periph_GPIO_Init(uint32_t RCC_APB2Periph,GPIO_TypeDef* GPIOx,uint16_t GPIO_Pin);
void Periph_GPIO_Init_IPU(uint32_t RCC_APB2Periph,GPIO_TypeDef* GPIOx,uint16_t GPIO_Pin);
void Periph_GPIO_Init_OD(uint32_t RCC_APB2Periph,GPIO_TypeDef* GPIOx,uint16_t GPIO_Pin);//开漏输出  不止可以输出若要进行输入，先输出1在读取输入数据寄存器

#endif
